using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class SessionTracker
{
    public static void Run()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        if (config is null)
        {
            return;
        }
        Directory.CreateDirectory(PilotPaths.Journal);
        Directory.CreateDirectory(PilotPaths.Logs);
        _mutex = new Mutex(false, @"Local\WorkPilotSessionTracker");
        if (!_mutex.WaitOne(0))
        {
            return;
        }
        var sessionId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var sessionFile = Path.Combine(PilotPaths.Journal, $"{config.UserName}-{sessionId}.jsonl");
        Log($"Session {sessionId} started for {config.UserName}.");
        var poll = Math.Max(2, config.PollSeconds);
        var worker = new Thread(() => Loop(sessionId, sessionFile, poll))
        {
            IsBackground = false,
            Name = "WorkPilot tracker"
        };
        worker.Start();
        WindowsAdmin.Show("Work session recording is on. This computer records the programs you use and idle time until you sign out. It does not record keystrokes or screenshots.");
    }

    private static Mutex? _mutex;

    private static void Loop(string sessionId, string sessionFile, int poll)
    {
        while (true)
        {
            try
            {
                var line = Capture(sessionId);
                File.AppendAllText(sessionFile, line + Environment.NewLine);
            }
            catch (Exception ex)
            {
                Log(ex.Message);
            }
            Thread.Sleep(TimeSpan.FromSeconds(poll));
        }
    }

    private static string Capture(string sessionId)
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
        return JsonSerializer.Serialize(payload);
    }

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
        public static uint IdleSeconds()
        {
            var info = new LastInputInfo { cbSize = (uint)Marshal.SizeOf<LastInputInfo>() };
            _ = GetLastInputInfo(ref info);
            return (unchecked((uint)Environment.TickCount) - info.dwTime) / 1000;
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
    }
}
