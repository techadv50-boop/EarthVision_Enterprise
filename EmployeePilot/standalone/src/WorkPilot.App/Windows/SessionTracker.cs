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
        var sessionStarted = DateTime.UtcNow;
        StatusServer.Start();
        StartLocalAlarm();
        var worker = new Thread(() => Loop(config, sessionId, sessionFile, poll, alarmAfter, sessionStarted))
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

    private static void Loop(PilotConfig config, string sessionId, string sessionFile, int poll, int alarmAfter, DateTime sessionStarted)
    {
        var clicks = 0;
        var activeSeconds = 0;
        var idleSeconds = 0;
        var countedUntil = DateTime.UtcNow;
        var leftDown = false;
        var rightDown = false;
        var lastLine = "";
        var recent = new List<string>();
        var nextJournal = DateTime.UtcNow;
        var nextConfig = DateTime.UtcNow;
        var startedLocal = sessionStarted.ToLocalTime().ToString("h:mm tt");
        var clock = new TimerControl();
        var appliedCommand = default(DateTime);
        DateTime? disconnectedSince = null;
        var reportToken = "";
        while (true)
        {
            try
            {
                if (DateTime.UtcNow >= nextConfig)
                {
                    var fresh = PilotConfigStore.Load(PilotPaths.Config);
                    if (fresh is not null && fresh.AlarmAfterSeconds >= 5)
                    {
                        alarmAfter = fresh.AlarmAfterSeconds;
                    }
                    nextConfig = DateTime.UtcNow.AddSeconds(2);
                }
                clicks += CountClick(ref leftDown, 0x01) + CountClick(ref rightDown, 0x02);
                var sample = Capture(sessionId);
                var idle = sample.IdleSeconds;
                var locked = sample.Locked;
                var working = ActivitySignal.IsWorking(idle, locked, alarmAfter);
                var now = DateTime.UtcNow;
                var disconnected = Native.IsSessionDisconnected();
                if (disconnected)
                {
                    disconnectedSince ??= now;
                }
                else
                {
                    disconnectedSince = null;
                }
                var sessionConnected = disconnectedSince is null || (now - disconnectedSince.Value).TotalSeconds < 15;
                var command = ReadCommand(ref appliedCommand);
                clock.Tick(sessionConnected, command);
                if ((clock.Running && !clock.BeginSession) || clock.ReportDue)
                {
                    if (clock.ReportDue || now >= nextJournal)
                    {
                        File.AppendAllText(sessionFile, sample.Line + Environment.NewLine);
                        nextJournal = now.AddSeconds(poll);
                    }
                }
                if (clock.ReportDue)
                {
                    reportToken = sessionId + "-" + now.Ticks;
                    WriteReport();
                }
                if (clock.BeginSession)
                {
                    sessionId = now.ToLocalTime().ToString("yyyyMMdd-HHmmss");
                    sessionFile = Path.Combine(PilotPaths.Journal, $"{config.UserName}-{sessionId}.jsonl");
                    sessionStarted = now;
                    startedLocal = sessionStarted.ToLocalTime().ToString("h:mm tt");
                    activeSeconds = 0;
                    idleSeconds = 0;
                    clicks = 0;
                    countedUntil = now;
                    recent.Clear();
                    lastLine = "";
                }
                var elapsed = (int)(now - countedUntil).TotalSeconds;
                if (clock.Running && elapsed > 0)
                {
                    SessionClock.Add(ref activeSeconds, ref idleSeconds, working, elapsed);
                    countedUntil = countedUntil.AddSeconds(elapsed);
                }
                _localBeep = clock.Running && !working ? 1 : 0;
                var line = $"{now.ToLocalTime():h:mm tt}  {(working ? "Working" : "Not working")}  {sample.Process}  {sample.Title}";
                if (!string.Equals(line, lastLine, StringComparison.Ordinal))
                {
                    recent.Add(line);
                    if (recent.Count > 8)
                    {
                        recent.RemoveAt(0);
                    }
                    lastLine = line;
                }
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
                    UpdatedUtc = now,
                    SessionStartedUtc = sessionStarted,
                    StartedLocal = startedLocal,
                    ActiveSeconds = activeSeconds,
                    SessionIdleSeconds = idleSeconds,
                    RecentLog = string.Join("\n", recent),
                    TimerRunning = clock.Running,
                    TimerNote = clock.Note,
                    ReportToken = reportToken
                });
            }
            catch (Exception ex)
            {
                Log(ex.Message);
            }
            Thread.Sleep(250);
        }
    }

    private static string? ReadCommand(ref DateTime appliedUtc)
    {
        try
        {
            if (!File.Exists(PilotPaths.CommandFile))
            {
                return null;
            }
            using var stream = new FileStream(PilotPaths.CommandFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var reader = new StreamReader(stream);
            var text = reader.ReadToEnd();
            if (!TimerCommand.TryParse(text, out var action, out var issued) || issued == appliedUtc)
            {
                return null;
            }
            appliedUtc = issued;
            return action;
        }
        catch
        {
            return null;
        }
    }

    private static void WriteReport()
    {
        try
        {
            var config = PilotConfigStore.Load(PilotPaths.Config);
            if (config is null)
            {
                return;
            }
            ReportFiles.WriteRecent(PilotPaths.Journal, PilotPaths.Reports, config, Environment.MachineName);
        }
        catch (Exception ex)
        {
            Log(ex.Message);
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
            process = Native.ForegroundProcessName();
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

        public static bool IsSessionDisconnected()
        {
            try
            {
                var sessionId = Process.GetCurrentProcess().SessionId;
                if (!WTSQuerySessionInformation(IntPtr.Zero, sessionId, 8, out var buffer, out _))
                {
                    return false;
                }
                try
                {
                    return Marshal.ReadInt32(buffer) == 4;
                }
                finally
                {
                    WTSFreeMemory(buffer);
                }
            }
            catch
            {
                return false;
            }
        }

        public static string ForegroundProcessName()
        {
            var hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
            {
                return "unknown.exe";
            }
            _ = GetWindowThreadProcessId(hwnd, out var pid);
            if (pid == 0)
            {
                return "unknown.exe";
            }
            var handle = OpenProcess(0x1000, false, pid);
            if (handle == IntPtr.Zero)
            {
                return "unknown.exe";
            }
            try
            {
                var buffer = new StringBuilder(1024);
                var size = buffer.Capacity;
                if (!QueryFullProcessImageName(handle, 0, buffer, ref size))
                {
                    return "unknown.exe";
                }
                var name = Path.GetFileName(buffer.ToString());
                return string.IsNullOrWhiteSpace(name) ? "unknown.exe" : name;
            }
            finally
            {
                CloseHandle(handle);
            }
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

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenProcess(uint access, bool inherit, uint processId);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQuerySessionInformation(IntPtr server, int sessionId, int infoClass, out IntPtr buffer, out int bytes);

        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr memory);
    }
}
