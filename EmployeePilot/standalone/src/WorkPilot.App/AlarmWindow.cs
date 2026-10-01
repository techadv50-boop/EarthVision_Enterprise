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

    public AlarmWindow(Func<LiveStatus> read, bool playSound = true)
    {
        _read = read;
        Title = "Employee activity";
        Width = 520;
        Height = 280;
        Topmost = true;
        Content = Build();
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

    private Control Build()
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center };
        row.Children.Add(_green);
        row.Children.Add(_red);
        var root = new StackPanel { Margin = new Avalonia.Thickness(20), Spacing = 16 };
        root.Children.Add(new TextBlock { Text = "Employee activity", FontSize = 22 });
        root.Children.Add(row);
        root.Children.Add(_detail);
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
        _detail.Text = $"{status.EmployeeName}\n{status.Program} — {status.Title}\nIdle {status.IdleSeconds} seconds · clicks {status.ClickCount}\nRed light after {status.AlarmAfterSeconds} seconds without the mouse or keyboard.";
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
