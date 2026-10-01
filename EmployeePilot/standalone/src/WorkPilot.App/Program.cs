using Avalonia;
using WorkPilot.Windows;

namespace WorkPilot;

public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        if (Has(args, "--track"))
        {
            if (!SessionTracker.Run())
            {
                return;
            }
            TrackMode = true;
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
            return;
        }
        if (Has(args, "--watch"))
        {
            WatchUrl = args.FirstOrDefault(arg => arg.StartsWith("http", StringComparison.OrdinalIgnoreCase))
                ?? "http://127.0.0.1:8777/status";
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
            return;
        }
        if (Has(args, "--report"))
        {
            ReportJob.Run();
            return;
        }
        if (OperatingSystem.IsWindows() && !WindowsAdmin.IsAdmin())
        {
            WindowsAdmin.RelaunchElevated();
            return;
        }
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static bool TrackMode { get; private set; }
    public static string? WatchUrl { get; private set; }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();

    private static bool Has(string[] args, string flag) =>
        args.Any(arg => string.Equals(arg, flag, StringComparison.OrdinalIgnoreCase));
}
