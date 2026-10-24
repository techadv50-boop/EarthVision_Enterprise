using System.Runtime.InteropServices;
using System.Threading;
using Avalonia;
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
    private readonly Border _green = Lamp("Working");
    private readonly Border _red = Lamp("Not working");
    private readonly TextBlock _active = Line("Active");
    private readonly TextBlock _idle = Line("Idle");
    private readonly TextBlock _idleNow = Line("Idle now");
    private readonly TextBlock _note = new() { FontSize = 12, Foreground = new SolidColorBrush(Color.Parse("#9B1C1C")) };
    private readonly CancellationTokenSource _stop = new();
    private readonly bool _lockClose;
    private volatile int _beeping;

    public AlarmWindow(Func<LiveStatus> read, bool playSound = true, bool lockClose = false)
    {
        _read = read;
        _lockClose = lockClose;
        Title = "Timer";
        SizeToContent = SizeToContent.WidthAndHeight;
        Topmost = true;
        CanResize = false;
        ShowInTaskbar = !lockClose;
        WindowStartupLocation = WindowStartupLocation.Manual;
        Background = Brushes.White;
        Content = Build();
        if (lockClose)
        {
            Closing += (_, eventArgs) => eventArgs.Cancel = true;
            PropertyChanged += (_, eventArgs) =>
            {
                if (eventArgs.Property == WindowStateProperty && WindowState == WindowState.Minimized)
                {
                    WindowState = WindowState.Normal;
                }
            };
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
        Opened += (_, _) =>
        {
            Place();
            Topmost = true;
            Activate();
        };
    }

    private Control Build()
    {
        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            HorizontalAlignment = HorizontalAlignment.Center
        };
        row.Children.Add(_green);
        row.Children.Add(_red);
        var root = new StackPanel { Margin = new Thickness(8, 6), Spacing = 2 };
        root.Children.Add(row);
        root.Children.Add(_active);
        root.Children.Add(_idle);
        root.Children.Add(_idleNow);
        root.Children.Add(_note);
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
        var running = fresh && status.TimerRunning;
        var working = running && status.Working;
        Paint(_green, working, "#148F3E");
        Paint(_red, running && !status.Working, "#C62828");
        _beeping = running && !status.Working ? 1 : 0;
        if (_lockClose)
        {
            Topmost = true;
        }
        if (!fresh)
        {
            _active.Text = "Active  —";
            _idle.Text = "Idle  —";
            _idleNow.Text = "Idle now  —";
            _note.Text = _lockClose ? "" : "No employee is signed in.";
            _note.IsVisible = _note.Text.Length > 0;
            return;
        }
        _active.Text = "Active  " + ReportText.FormatDuration(status.ActiveSeconds);
        _idle.Text = "Idle  " + ReportText.FormatDuration(status.SessionIdleSeconds);
        _idleNow.Text = "Idle now  " + status.IdleSeconds + " s";
        _idleNow.Foreground = status.IdleSeconds >= status.AlarmAfterSeconds
            ? new SolidColorBrush(Color.Parse("#C62828"))
            : Brushes.Black;
        _note.Text = running ? "" : (string.IsNullOrWhiteSpace(status.TimerNote) ? "Timer stopped" : status.TimerNote);
        _note.IsVisible = _note.Text.Length > 0;
        Title = working ? "Working" : running ? "Not working" : "Timer stopped";
    }

    private void Place()
    {
        var area = Screens?.Primary?.WorkingArea;
        if (area is { } work)
        {
            var width = double.IsNaN(Width) || Width < 1 ? 240 : Width;
            Position = new PixelPoint(work.X + Math.Max(0, work.Width - (int)width - 12), work.Y + 12);
        }
        if (_lockClose)
        {
            HideWindowButtons();
        }
    }

    private void HideWindowButtons()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }
        var handle = TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
        if (handle == IntPtr.Zero)
        {
            return;
        }
        const int styleIndex = -16;
        const long caption = 0x00C00000;
        const long systemMenu = 0x00080000;
        const long minimize = 0x00020000;
        const long maximize = 0x00010000;
        var style = GetWindowLongPtr(handle, styleIndex).ToInt64();
        SetWindowLongPtr(handle, styleIndex, new IntPtr((style | caption) & ~(systemMenu | minimize | maximize)));
        SetWindowPos(handle, IntPtr.Zero, 0, 0, 0, 0, 0x0027);
    }

    private static void Paint(Border lamp, bool on, string color)
    {
        lamp.Background = new SolidColorBrush(Color.Parse(on ? color : "#D9D9D9"));
        if (lamp.Child is TextBlock label)
        {
            label.Foreground = new SolidColorBrush(on ? Colors.White : Color.Parse("#555555"));
        }
    }

    private static Border Lamp(string label) => new()
    {
        Width = 112,
        Height = 28,
        CornerRadius = new CornerRadius(6),
        Background = new SolidColorBrush(Color.Parse("#D9D9D9")),
        Child = new TextBlock
        {
            Text = label,
            FontSize = 13,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = new SolidColorBrush(Color.Parse("#555555"))
        }
    };

    private static TextBlock Line(string name) => new()
    {
        Text = name + "  0 s",
        FontSize = 14
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

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr window, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr value);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
}
