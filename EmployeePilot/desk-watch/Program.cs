using Avalonia;
using WorkPilot.Windows;

namespace WorkPilot;

public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        AppDomain.CurrentDomain.UnhandledException += (_, eventArgs) => CrashLog.Write(eventArgs.ExceptionObject as Exception);
        try
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
        catch (Exception ex)
        {
            CrashLog.Write(ex);
        }
    }

    public static bool TrackMode { get; private set; }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<DeskApp>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();

    private static bool Has(string[] args, string flag) =>
        args.Any(arg => string.Equals(arg, flag, StringComparison.OrdinalIgnoreCase));
}
