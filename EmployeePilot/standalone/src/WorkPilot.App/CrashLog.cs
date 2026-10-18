namespace WorkPilot;

public static class CrashLog
{
    private static int _shown;

    public static void Write(Exception? exception)
    {
        if (exception is null)
        {
            return;
        }
        var text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + Environment.NewLine + exception + Environment.NewLine + Environment.NewLine;
        foreach (var path in Locations())
        {
            try
            {
                var folder = Path.GetDirectoryName(path);
                if (!string.IsNullOrWhiteSpace(folder))
                {
                    Directory.CreateDirectory(folder);
                }
                File.AppendAllText(path, text);
            }
            catch
            {
                // Try the next location.
            }
        }
        if (Interlocked.Exchange(ref _shown, 1) == 0)
        {
            Windows.WindowsAdmin.Show("WorkPilot hit a problem and kept a note in WorkPilot-crash.txt on your desktop.");
        }
    }

    private static IEnumerable<string> Locations()
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
        {
            yield return Path.Combine(desktop, "WorkPilot-crash.txt");
        }
        yield return Path.Combine(Windows.PilotPaths.Logs, "crash.txt");
    }
}
