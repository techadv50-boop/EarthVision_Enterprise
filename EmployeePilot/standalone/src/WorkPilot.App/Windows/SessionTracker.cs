using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class SessionTracker
{
    public static bool Run()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        if (config is null)
        {
            return false;
        }
        Directory.CreateDirectory(PilotPaths.Journal);
        Directory.CreateDirectory(PilotPaths.Logs);
        _mutex = new Mutex(false, @"Local\WorkPilotSessionTracker");
        if (!_mutex.WaitOne(0))
        {
            return false;
        }
        var sessionId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var sessionFile = Path.Combine(PilotPaths.Journal, $"{config.UserName}-{sessionId}.jsonl");
        Log($"Session {sessionId} started for {config.UserName}.");
        var poll = Math.Max(2, config.PollSeconds);
        var alarmAfter = config.AlarmAfterSeconds < 5 ? 30 : config.AlarmAfterSeconds;
        StatusServer.Start();
        StartLocalAlarm();
        var worker = new Thread(() => Loop(config, sessionId, sessionFile, poll, alarmAfter))
        {
            IsBackground = false,
            Name = "WorkPilot tracker"
        };
        worker.Start();
        return true;
    }

    private static Mutex? _mutex;
    private static volatile int _localBeep;

    private static void StartLocalAlarm()
    {
        var alarm = new Thread(() =>
        {
            while (true)
            {
                if (_localBeep == 1)
                {
                    SystemBeep.Tone();
                }
                Thread.Sleep(1200);
            }
        })
        {
            IsBackground = true,
            Name = "WorkPilot employee alarm"
        };
        alarm.Start();
    }

    private static void Loop(PilotConfig config, string sessionId, string sessionFile, int poll, int alarmAfter)
    {
        var clicks = 0;
        var leftDown = false;
        var rightDown = false;
        var nextJournal = DateTime.UtcNow;
        while (true)
        {
            try
            {
                clicks += CountClick(ref leftDown, 0x01) + CountClick(ref rightDown, 0x02);
                var sample = Capture(sessionId);
                var idle = sample.IdleSeconds;
                var locked = sample.Locked;
                var working = ActivitySignal.IsWorking(idle, locked, alarmAfter);
                _localBeep = working ? 0 : 1;
                LiveBoard.Publish(new LiveStatus
                {
                    SessionOpen = true,
                    Working = working,
                    IdleSeconds = idle,
                    AlarmAfterSeconds = alarmAfter,
                    Program = sample.Process,
                    Title = sample.Title,
                    ClickCount = clicks,
                    EmployeeName = config.EmployeeName,
                    UpdatedUtc = DateTime.UtcNow
                });
                if (DateTime.UtcNow >= nextJournal)
                {
                    File.AppendAllText(sessionFile, sample.Line + Environment.NewLine);
                    nextJournal = DateTime.UtcNow.AddSeconds(poll);
                }
            }
            catch (Exception ex)
            {
                Log(ex.Message);
            }
            Thread.Sleep(250);
        }
    }

    private static int CountClick(ref bool wasDown, int virtualKey)
    {
        var down = (Native.GetAsyncKeyState(virtualKey) & 0x8000) != 0;
        var clicked = down && !wasDown;
        wasDown = down;
        return clicked ? 1 : 0;
    }

    private static Sample Capture(string sessionId)
    {
        var idle = Native.IdleSeconds();
        var process = "unknown.exe";
        var title = "";
        try
        {
            title = Native.ForegroundTitle();
            var pid = Native.ForegroundProcessId();
            if (pid > 0)
            {
                process = Process.GetProcessById((int)pid).ProcessName;
                if (!process.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                {
                    process += ".exe";
                }
            }
        }
        catch
        {
            process = "unknown.exe";
        }
        title = title.Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (title.Length > 180)
        {
            title = title[..180];
        }
        var locked = process.Equals("LockApp.exe", StringComparison.OrdinalIgnoreCase)
            || process.Equals("LogonUI.exe", StringComparison.OrdinalIgnoreCase);
        var payload = new
        {
            sessionId,
            utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'"),
            idleSeconds = idle,
            process,
            title,
            locked
        };
        return new Sample(idle, locked, process, title, JsonSerializer.Serialize(payload));
    }

    private readonly record struct Sample(int IdleSeconds, bool Locked, string Process, string Title, string Line);

    private static void Log(string message)
    {
        try
        {
            Directory.CreateDirectory(PilotPaths.Logs);
            File.AppendAllText(Path.Combine(PilotPaths.Logs, "tracker.log"), $"{DateTime.UtcNow:o}  {message}{Environment.NewLine}");
        }
        catch
        {
            // The session file is the record that matters.
        }
    }

    private static class Native
    {
        public static int IdleSeconds()
        {
            var info = new LastInputInfo { cbSize = (uint)Marshal.SizeOf<LastInputInfo>() };
            if (!GetLastInputInfo(ref info))
            {
                return 0;
            }
            var idleMs = unchecked((uint)Environment.TickCount) - info.dwTime;
            return (int)Math.Min(idleMs / 1000, int.MaxValue);
        }

        public static string ForegroundTitle()
        {
            var hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
            {
                return "";
            }
            var buffer = new StringBuilder(512);
            _ = GetWindowText(hwnd, buffer, buffer.Capacity);
            return buffer.ToString();
        }

        public static uint ForegroundProcessId()
        {
            var hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
            {
                return 0;
            }
            _ = GetWindowThreadProcessId(hwnd, out var pid);
            return pid;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct LastInputInfo
        {
            public uint cbSize;
            public uint dwTime;
        }

        [DllImport("user32.dll")]
        private static extern bool GetLastInputInfo(ref LastInputInfo info);

        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

        [DllImport("user32.dll")]
        public static extern short GetAsyncKeyState(int virtualKey);
    }
}
