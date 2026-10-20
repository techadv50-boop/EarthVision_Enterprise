using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using WorkPilot.Core;
using WorkPilot.Windows;

namespace WorkPilot;

public class MainWindow : Window
{
    private static readonly (string Name, string Label)[] KnownPrograms =
    {
        ("chrome.exe", "Chrome"),
        ("msedge.exe", "Edge"),
        ("WINWORD.EXE", "Word"),
        ("EXCEL.EXE", "Excel"),
        ("POWERPNT.EXE", "PowerPoint"),
        ("notepad.exe", "Notepad"),
        ("AcroRd32.exe", "Adobe Reader"),
        ("Acrobat.exe", "Adobe Acrobat")
    };

    private readonly Border _content = new() { Background = Brushes.White };
    private readonly TextBlock _liveState = new() { Text = "Waiting for the employee.", FontSize = 20, FontWeight = FontWeight.SemiBold, Foreground = Brushes.White };
    private readonly TextBlock _liveDetail = new() { TextWrapping = TextWrapping.Wrap, FontSize = 16, Foreground = Brushes.White };
    private readonly Button _green = Lamp("Working");
    private readonly Button _red = Lamp("Not working");
    private readonly List<Button> _nav = new();
    private readonly CancellationTokenSource _stop = new();
    private readonly List<string> _extraPrograms = new();
    private volatile int _beeping;
    private int _busy;

    public MainWindow()
    {
        Title = "WorkPilot";
        Width = 1080;
        Height = 720;
        MinWidth = 860;
        MinHeight = 560;
        Background = new SolidColorBrush(Color.Parse("#F3F6F4"));
        Content = Build();
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
        timer.Tick += (_, _) => RefreshLive();
        timer.Start();
        new Thread(BeepLoop) { IsBackground = true, Name = "WorkPilot alarm" }.Start();
        Closed += (_, _) => _stop.Cancel();
        ShowPage("Live activity", LivePage());
        _ = Task.Run(TryRefreshInstalledCopy);
    }

    private Control Build()
    {
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(230)));
        root.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        root.RowDefinitions.Add(new RowDefinition(GridLength.Star));
        root.RowDefinitions.Add(new RowDefinition(new GridLength(120)));
        var side = new StackPanel { Spacing = 6, Margin = new Avalonia.Thickness(16) };
        side.Children.Add(new TextBlock { Text = "WorkPilot", FontSize = 22, FontWeight = FontWeight.SemiBold, Margin = new Avalonia.Thickness(8, 8, 8, 16) });
        AddNav(side, "Live activity", () => ShowPage("Live activity", LivePage()));
        AddNav(side, "Activity log", () => ShowPage("Activity log", LogPage()));
        AddNav(side, "Programs", () => ShowPage("Programs", ProgramsPage()));
        AddNav(side, "Storage", () => ShowPage("Storage", StoragePage()));
        AddNav(side, "Beep and time", () => ShowPage("Beep and time", TimerPage()));
        AddNav(side, "Employee login", () => ShowPage("Employee login", EmployeePage()));
        AddNav(side, "Folders", () => ShowPage("Folders", FoldersPage()));
        var sideHost = new Border { Background = new SolidColorBrush(Color.Parse("#E7EEE9")), Child = side };
        Grid.SetColumn(sideHost, 0);
        Grid.SetRow(sideHost, 0);
        Grid.SetRowSpan(sideHost, 2);
        Grid.SetColumn(_content, 1);
        Grid.SetRow(_content, 0);
        var strip = LiveStrip();
        Grid.SetColumn(strip, 1);
        Grid.SetRow(strip, 1);
        root.Children.Add(sideHost);
        root.Children.Add(_content);
        root.Children.Add(strip);
        return root;
    }

    private Control LiveStrip()
    {
        var lamps = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
        lamps.Children.Add(_green);
        lamps.Children.Add(_red);
        var words = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
        words.Children.Add(_liveState);
        words.Children.Add(_liveDetail);
        var row = new Grid { ColumnDefinitions = { new ColumnDefinition(GridLength.Auto), new ColumnDefinition(GridLength.Star) } };
        Grid.SetColumn(words, 1);
        words.Margin = new Avalonia.Thickness(16, 0, 0, 0);
        row.Children.Add(lamps);
        row.Children.Add(words);
        return new Border
        {
            Background = new SolidColorBrush(Color.Parse("#16382C")),
            Padding = new Avalonia.Thickness(16, 10),
            Child = row
        };
    }

    private void AddNav(StackPanel side, string label, Action open)
    {
        var button = new Button
        {
            Content = label,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Left,
            MinHeight = 44,
            FontSize = 16,
            Background = Brushes.Transparent,
            BorderThickness = new Avalonia.Thickness(0)
        };
        button.Click += (_, _) => open();
        _nav.Add(button);
        side.Children.Add(button);
    }

    private void ShowPage(string name, Control page)
    {
        foreach (var button in _nav)
        {
            var selected = string.Equals(button.Content as string, name, StringComparison.Ordinal);
            button.Background = new SolidColorBrush(Color.Parse(selected ? "#0F6B4C" : "#00000000"));
            button.Foreground = new SolidColorBrush(selected ? Colors.White : Color.Parse("#1C1C1C"));
        }
        _content.Child = new ScrollViewer { Content = page, Padding = new Avalonia.Thickness(28) };
    }

    private Control LivePage()
    {
        var page = Page("Live activity", "The employee sees this same green and red window on the desktop, with time worked and time idle. The bar at the bottom of your window shows that record while the employee is signed in. Red means they stopped, and this computer beeps.");
        page.Children.Add(new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 16,
            Text = "On the other computer, install Tailscale and sign in with the same account. Open Remote Desktop Connection. In Computer, type 100.109.247.33. For the user name, type DESKTOP-ENCM4H4\\employee1 and the employee password. The desktop that opens is this computer. The employee then uses the programs installed here."
        });
        return page;
    }

    private Control LogPage()
    {
        var body = new TextBlock { Text = "Reading the activity log...", TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        var open = new Button { Content = "Open the full report", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        open.Click += (_, _) => OpenReport(body);
        var page = Page("Activity log", "Idle time, sites, programs, and how long the employee has been on this computer.");
        page.Children.Add(open);
        page.Children.Add(body);
        _ = Task.Run(() =>
        {
            var text = JournalReader.Describe(PilotPaths.Journal);
            Dispatcher.UIThread.Post(() => body.Text = text);
        });
        return page;
    }

    private Control ProgramsPage()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        var allowed = new HashSet<string>(config?.AllowedPrograms ?? new List<string>(PilotDefaults.AllowedPrograms), StringComparer.OrdinalIgnoreCase);
        var boxes = new List<CheckBox>();
        var page = Page("Programs", "Tick the programs the employee may use. Save the list, then block the others only after a real work day looks right.");
        foreach (var program in KnownPrograms)
        {
            var box = new CheckBox { Content = program.Label, IsChecked = allowed.Contains(program.Name), FontSize = 16, Margin = new Avalonia.Thickness(0, 4) };
            box.Tag = program.Name;
            boxes.Add(box);
            page.Children.Add(box);
        }
        foreach (var extra in _extraPrograms.Concat(allowed).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (KnownPrograms.Any(program => program.Name.Equals(extra, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }
            var box = new CheckBox { Content = extra, IsChecked = true, FontSize = 16, Margin = new Avalonia.Thickness(0, 4) };
            box.Tag = extra;
            boxes.Add(box);
            page.Children.Add(box);
        }
        var add = new TextBox { Watermark = "Program file, for example WINWORD.EXE" };
        var addButton = new Button { Content = "Add program", MinHeight = 36 };
        addButton.Click += (_, _) =>
        {
            var name = (add.Text ?? "").Trim();
            if (name.Length == 0)
            {
                return;
            }
            if (!_extraPrograms.Contains(name, StringComparer.OrdinalIgnoreCase))
            {
                _extraPrograms.Add(name);
            }
            ShowPage("Programs", ProgramsPage());
        };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var save = new Button { Content = "Save allowed programs", MinHeight = 40 };
        var block = new Button { Content = "Save and block other programs", MinHeight = 40 };
        save.Click += async (_, _) => await RunButtons(new[] { save, block }, () => Task.Run(() => PilotSetup.UpdatePrograms(Selected(boxes), false, line => Post(status, line))));
        block.Click += async (_, _) => await RunButtons(new[] { save, block }, () => Task.Run(() => PilotSetup.UpdatePrograms(Selected(boxes), true, line => Post(status, line))));
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(save);
        actions.Children.Add(block);
        page.Children.Add(add);
        page.Children.Add(addButton);
        page.Children.Add(actions);
        page.Children.Add(status);
        return page;
    }

    private Control StoragePage()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        var quota = new TextBox { Text = (config?.QuotaGB ?? 80).ToString(), Watermark = "Gigabytes" };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        if (config is not null)
        {
            status.Text = $"Current limit: {config.QuotaGB} GB on {config.Volume} for {config.UserName}. The folder is {config.WorkFolder}.";
        }
        var apply = new Button { Content = "Apply storage limit", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        apply.Click += async (_, _) => await RunButtons(new[] { apply }, () =>
        {
            if (!int.TryParse(quota.Text, out var gb))
            {
                throw new InvalidOperationException("Enter the storage limit as a whole number of GB.");
            }
            return Task.Run(() => PilotSetup.UpdateQuota(gb, line => Post(status, line)));
        });
        var page = Page("Storage", "This is the disk space the employee can use on this computer.");
        page.Children.Add(Label("Storage in GB"));
        page.Children.Add(quota);
        page.Children.Add(apply);
        page.Children.Add(status);
        return page;
    }

    private Control TimerPage()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        var alarm = new TextBox { Text = (config?.AlarmAfterSeconds ?? 30).ToString() };
        var idle = new TextBox { Text = ((config?.IdleThresholdSeconds ?? 300) / 60).ToString() };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        var save = new Button { Content = "Save beep and idle time", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        save.Click += async (_, _) => await RunButtons(new[] { save }, () =>
        {
            if (!int.TryParse(alarm.Text, out var seconds))
            {
                throw new InvalidOperationException("Enter the beep time as a whole number of seconds.");
            }
            if (!int.TryParse(idle.Text, out var minutes))
            {
                throw new InvalidOperationException("Enter the idle time as a whole number of minutes.");
            }
            return Task.Run(() => PilotSetup.UpdateTimers(minutes, seconds, line => Post(status, line)));
        });
        var page = Page("Beep and time", "The beep uses seconds. The activity log uses minutes. A locked screen beeps immediately.");
        page.Children.Add(Label("Seconds without mouse or keyboard before the beep"));
        page.Children.Add(alarm);
        page.Children.Add(Label("Minutes before the activity log counts idle"));
        page.Children.Add(idle);
        page.Children.Add(save);
        page.Children.Add(status);
        return page;
    }

    private Control FoldersPage()
    {
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        var apply = new Button { Content = "Apply folder limits", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        apply.Click += async (_, _) => await RunButtons(new[] { apply }, () => Task.Run(() => PilotSetup.ApplyEmployeeLimits(line => Post(status, line))));
        var page = Page("Folders", "The employee can open Documents, Downloads, Desktop, and Control Panel. Drive C, the Windows folder, and Program Files stay closed. Installed programs cannot be removed. The time window stays open.");
        page.Children.Add(apply);
        page.Children.Add(status);
        return page;
    }

    private Control EmployeePage()
    {
        var fullName = new TextBox { Text = "Pilot Employee" };
        var userName = new TextBox { Text = "employee1" };
        var password = new TextBox { PasswordChar = '●' };
        var confirm = new TextBox { PasswordChar = '●' };
        var quota = new TextBox { Text = "80" };
        var idle = new TextBox { Text = "1" };
        var alarm = new TextBox { Text = "30" };
        var log = new TextBox { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Height = 220 };
        var setup = new Button { Content = "Set up this computer", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        setup.Click += async (_, _) => await RunButtons(new[] { setup }, () =>
        {
            if ((password.Text ?? "") != (confirm.Text ?? ""))
            {
                throw new InvalidOperationException("The passwords did not match.");
            }
            if (!int.TryParse(quota.Text, out var quotaGb) || !int.TryParse(idle.Text, out var idleMinutes) || !int.TryParse(alarm.Text, out var alarmSeconds))
            {
                throw new InvalidOperationException("Enter storage, idle minutes, and beep seconds as whole numbers.");
            }
            var request = new PilotRequest((fullName.Text ?? "").Trim(), (userName.Text ?? "").Trim(), password.Text ?? "", quotaGb, idleMinutes, alarmSeconds);
            password.Text = "";
            confirm.Text = "";
            return Task.Run(() => PilotSetup.Run(request, line => Post(log, line)));
        });
        var page = Page("Employee login", "Use this when the employee login still needs to be created. The password needs 8 characters, a capital letter, a small letter, and a number, with no spaces.");
        page.Children.Add(Label("Employee full name"));
        page.Children.Add(fullName);
        page.Children.Add(Label("Windows login"));
        page.Children.Add(userName);
        page.Children.Add(Label("Password"));
        page.Children.Add(password);
        page.Children.Add(Label("Confirm password"));
        page.Children.Add(confirm);
        page.Children.Add(Label("Storage in GB"));
        page.Children.Add(quota);
        page.Children.Add(Label("Idle minutes for the activity log"));
        page.Children.Add(idle);
        page.Children.Add(Label("Seconds before the beep"));
        page.Children.Add(alarm);
        page.Children.Add(setup);
        page.Children.Add(log);
        return page;
    }

    private static StackPanel Page(string title, string intro)
    {
        var page = new StackPanel { Spacing = 12, MaxWidth = 720 };
        page.Children.Add(new TextBlock { Text = title, FontSize = 28, FontWeight = FontWeight.SemiBold });
        page.Children.Add(new TextBlock { Text = intro, TextWrapping = TextWrapping.Wrap, FontSize = 16 });
        return page;
    }

    private static TextBlock Label(string text) => new() { Text = text, FontSize = 15 };

    private static Button Lamp(string label) => new()
    {
        Content = label,
        MinWidth = 150,
        MinHeight = 56,
        FontSize = 16,
        IsHitTestVisible = false,
        Background = new SolidColorBrush(Color.Parse("#D9D9D9"))
    };

    private static List<string> Selected(IEnumerable<CheckBox> boxes) =>
        boxes.Where(box => box.IsChecked == true).Select(box => box.Tag as string ?? "").Where(name => name.Length > 0).ToList();

    private async void RefreshLive()
    {
        if (Interlocked.Exchange(ref _busy, 1) == 1)
        {
            return;
        }
        LiveStatus status;
        try
        {
            status = await Task.Run(() => LiveBoard.ReadUrl("http://127.0.0.1:8777/status"));
        }
        catch
        {
            status = new LiveStatus { SessionOpen = false, Working = true };
        }
        finally
        {
            Interlocked.Exchange(ref _busy, 0);
        }
        try
        {
            ApplyLive(status);
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex);
        }
    }

    private void ApplyLive(LiveStatus status)
    {
        var fresh = LiveBoard.IsFresh(status);
        var working = fresh && status.Working;
        Paint(_green, working, "#148F3E");
        Paint(_red, fresh && !status.Working, "#C62828");
        _beeping = fresh && !status.Working ? 1 : 0;
        if (!fresh)
        {
            _liveState.Text = "No employee is signed in.";
            _liveDetail.Text = "Sign in as the employee on this computer. This page then shows the program, the site, the idle time, and the time spent on the system.";
            return;
        }
        var elapsed = status.SessionStartedUtc > DateTime.UnixEpoch
            ? ReportText.FormatDuration((int)Math.Max(0, (DateTime.UtcNow - status.SessionStartedUtc).TotalSeconds))
            : "not recorded yet";
        var started = !string.IsNullOrWhiteSpace(status.StartedLocal)
            ? status.StartedLocal
            : status.SessionStartedUtc > DateTime.UnixEpoch
                ? status.SessionStartedUtc.ToLocalTime().ToString("h:mm tt")
                : "not recorded yet";
        var place = IsBrowser(status.Program ?? "") ? "Site" : "Window";
        var project = string.IsNullOrWhiteSpace(status.Title) ? "No project title yet" : status.Title;
        _liveState.Text = working ? "Working" : "Not working";
        _liveDetail.Text = $"Started {started}    Time worked {ReportText.FormatDuration(status.ActiveSeconds)}    Time idle {ReportText.FormatDuration(status.SessionIdleSeconds)}\nProgram: {status.Program}    {place}: {project}\nTime on computer {elapsed}    Clicks {status.ClickCount}";
    }

    private static bool IsBrowser(string? process) =>
        !string.IsNullOrEmpty(process)
        && (process.Contains("chrome", StringComparison.OrdinalIgnoreCase) || process.Contains("msedge", StringComparison.OrdinalIgnoreCase));

    private static void Paint(Button button, bool on, string color)
    {
        button.Background = new SolidColorBrush(Color.Parse(on ? color : "#D9D9D9"));
        button.Foreground = new SolidColorBrush(on ? Colors.White : Color.Parse("#555555"));
    }

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

    private void OpenReport(TextBlock status)
    {
        var path = Path.Combine(PilotPaths.Reports, "latest.html");
        if (!File.Exists(path))
        {
            status.Text = "No report yet. Sign in as the employee, use the computer, then sign out and wait one minute.";
            return;
        }
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path) { UseShellExecute = true });
    }

    private static void Post(TextBlock target, string line)
    {
        Dispatcher.UIThread.Post(() => target.Text = string.IsNullOrEmpty(target.Text) ? line : target.Text + Environment.NewLine + line);
    }

    private static void Post(TextBox target, string line)
    {
        Dispatcher.UIThread.Post(() =>
        {
            target.Text = string.IsNullOrEmpty(target.Text) ? line : target.Text + Environment.NewLine + line;
            target.CaretIndex = target.Text?.Length ?? 0;
        });
    }

    private async Task RunButtons(IReadOnlyList<Button> buttons, Func<Task> work)
    {
        foreach (var button in buttons)
        {
            button.IsEnabled = false;
        }
        try
        {
            await work();
        }
        catch (Exception ex)
        {
            if (buttons.Count > 0)
            {
                buttons[0].Content = buttons[0].Content;
            }
            var page = _content.Child;
            var notice = new TextBlock { Text = ex.Message, TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Color.Parse("#9B1C1C")) };
            if (page is ScrollViewer viewer && viewer.Content is StackPanel stack)
            {
                stack.Children.Add(notice);
            }
        }
        finally
        {
            foreach (var button in buttons)
            {
                button.IsEnabled = true;
            }
        }
    }

    private static void TryRefreshInstalledCopy()
    {
        try
        {
            PilotSetup.RefreshInstalledCopy();
            PilotSetup.RepairRecordingAccess();
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex);
            if (!WindowsAdmin.IsAdmin())
            {
                WindowsAdmin.Show("This update is open, but the employee window still uses the older copy. Sign the employee out, close this window, right-click WorkPilot.exe, and choose Run as administrator. Approve the prompt. The employee should sign in again.");
            }
        }
        try
        {
            PilotSetup.ApplyEmployeeLimits(static _ => { });
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex);
        }
    }
}
