using System.Diagnostics;
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
    private readonly Button _green = Lamp("Working");
    private readonly Button _red = Lamp("Not working");
    private readonly TextBlock _worked = new() { FontSize = 28, FontWeight = FontWeight.SemiBold, Text = "Time worked  0 s" };
    private readonly TextBlock _idle = new() { FontSize = 28, FontWeight = FontWeight.SemiBold, Text = "Time idle  0 s" };
    private readonly TextBlock _detail = new() { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
    private readonly CancellationTokenSource _stop = new();
    private readonly bool _lockClose;
    private volatile int _beeping;

    public AlarmWindow(Func<LiveStatus> read, bool playSound = true, bool lockClose = false)
    {
        _read = read;
        _lockClose = lockClose;
        Title = "Employee activity";
        Width = 520;
        Height = lockClose ? 460 : 400;
        Topmost = true;
        WindowStartupLocation = WindowStartupLocation.Manual;
        CanResize = !lockClose;
        Content = Build(lockClose);
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
        Opened += (_, _) => Place();
    }

    private Control Build(bool showSignOut)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center };
        row.Children.Add(_green);
        row.Children.Add(_red);
        var root = new StackPanel { Margin = new Avalonia.Thickness(20), Spacing = 10 };
        root.Children.Add(new TextBlock { Text = "Your time on this computer", FontSize = 22 });
        root.Children.Add(row);
        root.Children.Add(_worked);
        root.Children.Add(_idle);
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
        var running = fresh && status.TimerRunning;
        var working = running && status.Working;
        Paint(_green, working, "#148F3E");
        Paint(_red, running && !status.Working, "#C62828");
        _beeping = running && !status.Working ? 1 : 0;
        if (!fresh)
        {
            _worked.Text = "Time worked  —";
            _idle.Text = "Time idle  —";
            _detail.Text = _lockClose
                ? "The time record is starting."
                : "No employee is signed in on the work computer.";
            Title = "Employee activity";
            return;
        }
        var state = running ? (working ? "Working" : "Not working") : "Timer stopped";
        Title = $"{state}  ·  worked {ReportText.FormatDuration(status.ActiveSeconds)}";
        _worked.Text = "Time worked  " + ReportText.FormatDuration(status.ActiveSeconds);
        _idle.Text = "Time idle  " + ReportText.FormatDuration(status.SessionIdleSeconds);
        _detail.Text = Describe(status);
    }

    private void Place()
    {
        var area = Screens?.Primary?.WorkingArea;
        if (area is { } work)
        {
            Position = new PixelPoint(work.X + Math.Max(0, work.Width - (int)Width - 24), work.Y + Math.Max(0, work.Height - (int)Height - 24));
        }
        if (_lockClose)
        {
            HideCloseButton();
        }
    }

    private void HideCloseButton()
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
        const int systemMenu = 0x00080000;
        var style = GetWindowLongPtr(handle, styleIndex);
        SetWindowLongPtr(handle, styleIndex, new IntPtr(style.ToInt64() & ~systemMenu));
        SetWindowPos(handle, IntPtr.Zero, 0, 0, 0, 0, 0x0027);
    }

    private static string Describe(LiveStatus status)
    {
        var program = status.Program ?? "";
        var place = program.Contains("chrome", StringComparison.OrdinalIgnoreCase)
            || program.Contains("msedge", StringComparison.OrdinalIgnoreCase)
            ? "Site"
            : "Window";
        var started = string.IsNullOrWhiteSpace(status.StartedLocal) ? "the sign-in time" : status.StartedLocal;
        var note = string.IsNullOrWhiteSpace(status.TimerNote) ? "" : status.TimerNote + "\n";
        var log = string.IsNullOrWhiteSpace(status.RecentLog) ? "" : "\n\n" + status.RecentLog;
        return $"{note}Started {started}\n{program} — {place}: {status.Title}\nClicks {status.ClickCount}. Red light after {status.AlarmAfterSeconds} seconds.{log}";
    }

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr window, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr value);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

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
