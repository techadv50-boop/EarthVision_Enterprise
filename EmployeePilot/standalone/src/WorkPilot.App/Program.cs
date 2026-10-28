using Avalonia;
using WorkPilot.Windows;

namespace WorkPilot;

public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        AppDomain.CurrentDomain.UnhandledException += (_, eventArgs) => CrashLog.Write(eventArgs.ExceptionObject as Exception);
        TaskScheduler.UnobservedTaskException += (_, eventArgs) =>
        {
            eventArgs.SetObserved();
            if (!IsClosedConnection(eventArgs.Exception))
            {
                CrashLog.Write(eventArgs.Exception, notify: false);
            }
        };
        try
        {
            Run(args);
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex);
        }
    }

    private static void Run(string[] args)
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

    private static bool IsClosedConnection(Exception exception)
    {
        if (exception is AggregateException aggregate)
        {
            return aggregate.InnerExceptions.Count > 0 && aggregate.InnerExceptions.All(IsClosedConnection);
        }
        if (exception is System.Net.Sockets.SocketException socket && socket.SocketErrorCode == System.Net.Sockets.SocketError.ConnectionReset)
        {
            return true;
        }
        if (exception is IOException && exception.Message.Contains("forcibly closed", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        return exception.InnerException is not null && IsClosedConnection(exception.InnerException);
    }
}
