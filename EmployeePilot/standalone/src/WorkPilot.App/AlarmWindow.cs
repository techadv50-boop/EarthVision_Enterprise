using System.Diagnostics;
using System.Threading;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using WorkPilot.Core;
using WorkPilot.Windows;

namespace WorkPilot;

public class AlarmWindow : Window
{
    private readonly Func<LiveStatus> _read;
    private readonly Button _green = Lamp("Working");
    private readonly Button _red = Lamp("Not working");
    private readonly TextBlock _detail = new() { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
    private readonly CancellationTokenSource _stop = new();
    private volatile int _beeping;

    public AlarmWindow(Func<LiveStatus> read, bool playSound = true, bool lockClose = false)
    {
        _read = read;
        Title = "Employee activity";
        Width = 560;
        Height = lockClose ? 480 : 380;
        Topmost = true;
        Content = Build(lockClose);
        if (lockClose)
        {
            Closing += (_, eventArgs) => eventArgs.Cancel = true;
        }
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
        timer.Tick += (_, _) => Refresh();
        timer.Start();
        if (playSound)
        {
            var alarm = new Thread(BeepLoop) { IsBackground = true, Name = "WorkPilot alarm" };
            alarm.Start();
        }
        Closed += (_, _) => _stop.Cancel();
    }

    private Control Build(bool showSignOut)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center };
        row.Children.Add(_green);
        row.Children.Add(_red);
        var root = new StackPanel { Margin = new Avalonia.Thickness(20), Spacing = 12 };
        root.Children.Add(new TextBlock { Text = "Employee activity", FontSize = 22 });
        root.Children.Add(row);
        root.Children.Add(_detail);
        if (showSignOut)
        {
            var signOut = new Button
            {
                Content = "Sign out",
                MinWidth = 160,
                MinHeight = 40,
                FontSize = 16,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            signOut.Click += (_, _) => SignOut();
            root.Children.Add(signOut);
        }
        return root;
    }

    private int _busy;

    private async void Refresh()
    {
        if (Interlocked.Exchange(ref _busy, 1) == 1)
        {
            return;
        }
        LiveStatus status;
        try
        {
            status = await Task.Run(_read);
        }
        catch
        {
            status = new LiveStatus { SessionOpen = false, Working = true };
        }
        finally
        {
            Interlocked.Exchange(ref _busy, 0);
        }
        var fresh = LiveBoard.IsFresh(status);
        var working = fresh && status.Working;
        Paint(_green, working, "#148F3E");
        Paint(_red, fresh && !status.Working, "#C62828");
        _beeping = fresh && !status.Working ? 1 : 0;
        if (!fresh)
        {
            _detail.Text = "No employee is signed in on the work computer.";
            Title = "Employee activity";
            return;
        }
        var state = working ? "Working" : "Not working";
        Title = state;
        _detail.Text = Describe(status);
    }

    private static string Describe(LiveStatus status)
    {
        var place = status.Program.Contains("chrome", StringComparison.OrdinalIgnoreCase)
            || status.Program.Contains("msedge", StringComparison.OrdinalIgnoreCase)
            ? "Site"
            : "Window";
        var log = string.IsNullOrWhiteSpace(status.RecentLog) ? "" : "\n\n" + status.RecentLog;
        return $"{status.EmployeeName}\nStarted {status.StartedLocal}\nActive {ReportText.FormatDuration(status.ActiveSeconds)}\nIdle {ReportText.FormatDuration(status.SessionIdleSeconds)}\n{status.Program} — {place}: {status.Title}\nClicks {status.ClickCount}. Red light after {status.AlarmAfterSeconds} seconds.{log}";
    }

    private static void SignOut()
    {
        Process.Start(new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "shutdown.exe"), "/l")
        {
            UseShellExecute = false,
            CreateNoWindow = true
        });
    }

    private static void Paint(Button button, bool on, string color)
    {
        button.Background = new SolidColorBrush(Color.Parse(on ? color : "#D9D9D9"));
        button.Foreground = new SolidColorBrush(on ? Colors.White : Color.Parse("#555555"));
    }

    private static Button Lamp(string label) => new()
    {
        Content = label,
        MinWidth = 200,
        MinHeight = 72,
        FontSize = 20,
        IsHitTestVisible = false,
        Background = new SolidColorBrush(Color.Parse("#D9D9D9"))
    };

    private void BeepLoop()
    {
        while (!_stop.IsCancellationRequested)
        {
            if (_beeping == 1)
            {
                SystemBeep.Tone();
            }
            Thread.Sleep(1200);
        }
    }
}
