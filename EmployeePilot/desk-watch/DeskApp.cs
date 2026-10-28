using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using WorkPilot.Windows;

namespace WorkPilot;

public class DeskApp : Application
{
    public override void Initialize()
    {
        Styles.Add(new FluentTheme());
        RequestedThemeVariant = ThemeVariant.Light;
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            Avalonia.Threading.Dispatcher.UIThread.UnhandledException += (_, eventArgs) =>
            {
                CrashLog.Write(eventArgs.Exception);
                eventArgs.Handled = true;
            };
            desktop.MainWindow = Program.TrackMode
                ? new AlarmWindow(LiveBoard.ReadLocal, playSound: false, lockClose: true)
                : new DeskWindow();
        }
        base.OnFrameworkInitializationCompleted();
    }
}
