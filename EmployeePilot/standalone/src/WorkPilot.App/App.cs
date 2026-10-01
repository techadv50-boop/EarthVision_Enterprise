using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using WorkPilot.Windows;

namespace WorkPilot;

public class App : Application
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
            if (Program.TrackMode)
            {
                desktop.MainWindow = new AlarmWindow(LiveBoard.ReadLocal, playSound: false);
            }
            else if (!string.IsNullOrWhiteSpace(Program.WatchUrl))
            {
                var address = Program.WatchUrl;
                desktop.MainWindow = new AlarmWindow(() => LiveBoard.ReadUrl(address));
            }
            else
            {
                desktop.MainWindow = new MainWindow();
            }
        }
        base.OnFrameworkInitializationCompleted();
    }
}
