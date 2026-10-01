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
            SessionTracker.Run();
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

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();

    private static bool Has(string[] args, string flag) =>
        args.Any(arg => string.Equals(arg, flag, StringComparison.OrdinalIgnoreCase));
}
