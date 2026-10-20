using Avalonia;
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
    private readonly Border _green = Lamp("Working");
    private readonly Border _red = Lamp("Not working");
    private readonly List<Button> _nav = new();
    private readonly CancellationTokenSource _stop = new();
    private readonly List<string> _extraPrograms = new();
    private readonly List<string> _extraFolders = new();
    private volatile int _beeping;
    private int _busy;
    private string _reportToken = "";
    private AlarmWindow? _employeeTimer;

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
        Opened += (_, _) => ShowEmployeeTimer();
        ShowPage("Live activity", LivePage());
        _ = Task.Run(TryRefreshInstalledCopy);
    }

    private Control Build()
    {
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(230)));
        root.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        root.RowDefinitions.Add(new RowDefinition(GridLength.Star));
        root.RowDefinitions.Add(new RowDefinition(new GridLength(188)));
        var side = new StackPanel { Spacing = 6, Margin = new Avalonia.Thickness(16) };
        side.Children.Add(new TextBlock { Text = "WorkPilot", FontSize = 22, FontWeight = FontWeight.SemiBold, Margin = new Avalonia.Thickness(8, 8, 8, 16) });
        AddNav(side, "Live activity", () => ShowPage("Live activity", LivePage()));
        AddNav(side, "Activity log", () => ShowPage("Activity log", LogPage()));
        AddNav(side, "Programs", () => ShowPage("Programs", ProgramsPage()));
        AddNav(side, "Storage", () => ShowPage("Storage", StoragePage()));
        AddNav(side, "Beep and time", () => ShowPage("Beep and time", TimerPage()));
        AddNav(side, "Employee login", () => ShowPage("Employee login", EmployeePage()));
        AddNav(side, "Folders", () => ShowPage("Folders", FoldersPage()));
        AddNav(side, "Days", () => ShowPage("Days", DaysPage()));
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
        var actions = new StackPanel { Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
        var stopTimer = new Button { Content = "Stop timer", MinWidth = 120, MinHeight = 40 };
        var resetTimer = new Button { Content = "Reset timer", MinWidth = 120, MinHeight = 40 };
        stopTimer.Click += (_, _) => SendTimer("stop");
        resetTimer.Click += (_, _) => SendTimer("reset");
        actions.Children.Add(stopTimer);
        actions.Children.Add(resetTimer);
        var row = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition(GridLength.Auto),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Auto)
            }
        };
        Grid.SetColumn(words, 1);
        Grid.SetColumn(actions, 2);
        words.Margin = new Avalonia.Thickness(16, 0, 16, 0);
        row.Children.Add(lamps);
        row.Children.Add(words);
        row.Children.Add(actions);
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
        var page = Page("Live activity", "The employee has the same small timer in a corner of the desktop. You can drag it, and the employee cannot close or minimize it. Active and Idle are today's totals in Pakistan time. They continue when the employee signs in again on the same date, and they return to zero at midnight. Idle now is the current pause. At 30 seconds the computer beeps. Days lists the last 30 dates.");
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
        save.Click += async (_, _) =>
        {
            var programs = Selected(boxes);
            await RunButtons(new[] { save, block }, () => Task.Run(() => PilotSetup.UpdatePrograms(programs, false, line => Post(status, line))));
        };
        block.Click += async (_, _) =>
        {
            var programs = Selected(boxes);
            await RunButtons(new[] { save, block }, () => Task.Run(() => PilotSetup.UpdatePrograms(programs, true, line => Post(status, line))));
        };
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
        var page = Page("Beep and time", "The seconds box controls the beep and the red light. The minutes box does not change the beep. It is only for the written activity report.");
        page.Children.Add(Label("Seconds with no mouse or keyboard before the beep and the red light"));
        page.Children.Add(alarm);
        page.Children.Add(new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 16,
            Text = "Example: 30 means the light turns red and the beep starts after 30 seconds. The minutes box below is a different rule. A pause shorter than that many minutes still counts as working in the activity report. A pause that reaches that many minutes counts as idle in the report. If you enter 1, the report calls a pause idle after 1 minute, while the beep still follows the seconds box."
        });
        page.Children.Add(Label("Minutes before the written report calls a pause idle"));
        page.Children.Add(idle);
        page.Children.Add(save);
        page.Children.Add(status);
        return page;
    }

    private void ShowEmployeeTimer()
    {
        if (_employeeTimer is not null)
        {
            return;
        }
        _employeeTimer = new AlarmWindow(() => LiveBoard.ReadUrl("http://127.0.0.1:8777/status"), playSound: false, lockClose: false);
        _employeeTimer.Show();
    }

    private Control DaysPage()
    {
        var body = new TextBlock { Text = "Choose a date.", TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        var list = new StackPanel { Spacing = 4 };
        var dates = ConnectedDates();
        if (dates.Count == 0)
        {
            body.Text = "No connected day yet. A date appears here only after the employee signs in and the timer runs. A day off, such as a Sunday with no sign-in, is left out.";
        }
        foreach (var date in dates)
        {
            var chosen = date;
            var button = new Button
            {
                Content = chosen.ToString("ddd d MMM yyyy"),
                MinHeight = 34,
                HorizontalAlignment = HorizontalAlignment.Left
            };
            button.Click += async (_, _) =>
            {
                body.Text = "Reading " + chosen.ToString("d MMMM yyyy") + "...";
                var text = await Task.Run(() => DescribeDay(chosen));
                body.Text = text;
            };
            list.Children.Add(button);
        }
        var page = Page("Days", "Only days when the employee signed in and the timer ran. A day with no connection is not listed. Choose a date to see active time, idle time, programs, and the sites or windows.");
        page.Children.Add(list);
        page.Children.Add(body);
        return page;
    }

    private static IReadOnlyList<DateOnly> ConnectedDates()
    {
        var files = Directory.Exists(PilotPaths.Days)
            ? Directory.GetFiles(PilotPaths.Days, "*.json")
            : Array.Empty<string>();
        var journalDates = new List<DateOnly>();
        if (Directory.Exists(PilotPaths.Journal))
        {
            foreach (var file in Directory.GetFiles(PilotPaths.Journal, "*.jsonl"))
            {
                foreach (var line in File.ReadLines(file))
                {
                    if (string.IsNullOrWhiteSpace(line))
                    {
                        continue;
                    }
                    try
                    {
                        using var document = System.Text.Json.JsonDocument.Parse(line);
                        if (document.RootElement.TryGetProperty("utc", out var utcText)
                            && DateTime.TryParse(utcText.GetString(), null, System.Globalization.DateTimeStyles.AdjustToUniversal | System.Globalization.DateTimeStyles.AssumeUniversal, out var utc))
                        {
                            journalDates.Add(PakistanClock.Today(utc));
                        }
                    }
                    catch (System.Text.Json.JsonException)
                    {
                    }
                    break;
                }
            }
        }
        return PakistanClock.ConnectedDays(files, journalDates);
    }

    private static string DescribeDay(DateOnly date)
    {
        DayTotals? saved = null;
        var path = Path.Combine(PilotPaths.Days, date.ToString("yyyy-MM-dd") + ".json");
        if (File.Exists(path))
        {
            try
            {
                saved = System.Text.Json.JsonSerializer.Deserialize<DayTotals>(File.ReadAllText(path), PilotConfigStore.Json);
            }
            catch (System.Text.Json.JsonException)
            {
                saved = null;
            }
        }
        var samples = new List<ActivitySample>();
        if (Directory.Exists(PilotPaths.Journal))
        {
            foreach (var file in Directory.GetFiles(PilotPaths.Journal, "*.jsonl"))
            {
                samples.AddRange(ReportFiles.ReadSamples(file).Where(sample => PakistanClock.Today(sample.Utc) == date));
            }
        }
        var config = PilotConfigStore.Load(PilotPaths.Config);
        var totals = saved ?? DayReport.FromSamples(date, samples, config?.AlarmAfterSeconds ?? 30);
        return DayReport.Describe(date, totals, samples);
    }

    private Control FoldersPage()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        var allowed = new HashSet<string>(config?.AllowedFolders ?? new List<string>(FolderAccess.BuiltIn), StringComparer.OrdinalIgnoreCase);
        var choices = new List<string>(FolderAccess.BuiltIn);
        foreach (var drive in DriveInfo.GetDrives())
        {
            if (!drive.IsReady || drive.DriveType != DriveType.Fixed || drive.Name.Length == 0)
            {
                continue;
            }
            var name = drive.Name.TrimEnd('\\');
            if (!choices.Contains(name, StringComparer.OrdinalIgnoreCase))
            {
                choices.Add(name);
            }
        }
        foreach (var extra in _extraFolders.Concat(allowed))
        {
            if (!choices.Contains(extra, StringComparer.OrdinalIgnoreCase))
            {
                choices.Add(extra);
            }
        }
        var boxes = new List<CheckBox>();
        var page = Page("Folders", "Tick the places the employee may open. Leave a place unticked to keep it closed. Drive C includes the Windows folder and Program Files. Uninstall stays blocked either way. Sign the employee out and back in after you save.");
        foreach (var choice in choices)
        {
            var box = new CheckBox
            {
                Content = FolderLabel(choice),
                IsChecked = allowed.Contains(choice),
                FontSize = 16,
                Margin = new Thickness(0, 4),
                Tag = choice
            };
            boxes.Add(box);
            page.Children.Add(box);
        }
        var add = new TextBox { Watermark = "Another folder, for example D:\\Projects" };
        var addButton = new Button { Content = "Add folder", MinHeight = 36 };
        addButton.Click += (_, _) =>
        {
            var path = (add.Text ?? "").Trim();
            if (path.Length == 0)
            {
                return;
            }
            if (!_extraFolders.Contains(path, StringComparer.OrdinalIgnoreCase))
            {
                _extraFolders.Add(path);
            }
            ShowPage("Folders", FoldersPage());
        };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
        var apply = new Button { Content = "Save folder access", MinHeight = 40, HorizontalAlignment = HorizontalAlignment.Left };
        apply.Click += async (_, _) =>
        {
            var folders = Selected(boxes);
            await RunButtons(new[] { apply, addButton }, () => Task.Run(() => PilotSetup.UpdateFolders(folders, line => Post(status, line))));
        };
        page.Children.Add(add);
        page.Children.Add(addButton);
        page.Children.Add(apply);
        page.Children.Add(status);
        return page;
    }

    private static string FolderLabel(string choice) => choice.Length == 2 && choice[1] == ':'
        ? "Drive " + char.ToUpperInvariant(choice[0])
        : choice;

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

    private static Border Lamp(string label) => new()
    {
        Width = 132,
        Height = 44,
        CornerRadius = new CornerRadius(6),
        Background = new SolidColorBrush(Color.Parse("#D9D9D9")),
        Child = new TextBlock
        {
            Text = label,
            FontSize = 14,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        }
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
        var running = fresh && status.TimerRunning;
        var working = running && status.Working;
        Paint(_green, working, "#148F3E");
        Paint(_red, running && !status.Working, "#C62828");
        _beeping = running && !status.Working ? 1 : 0;
        SaveReportIfNeeded(status);
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
        var note = string.IsNullOrWhiteSpace(status.TimerNote) ? "" : status.TimerNote + "\n";
        _liveState.Text = running ? (working ? "Working" : "Not working") : "Timer stopped";
        _liveDetail.Text = $"{note}Active {ReportText.FormatDuration(status.ActiveSeconds)}    Idle {ReportText.FormatDuration(status.SessionIdleSeconds)}    Idle now {status.IdleSeconds} s\nProgram: {status.Program}    {place}: {project}\nStarted {started}    Time on computer {elapsed}";
    }

    private void SendTimer(string action)
    {
        try
        {
            PilotSetup.WriteTimerCommand(action);
            _liveState.Text = action == "reset" ? "Timer reset" : "Timer stopping";
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex, notify: false);
            _liveDetail.Text = ex.Message;
        }
    }

    private void SaveReportIfNeeded(LiveStatus status)
    {
        if (string.IsNullOrWhiteSpace(status.ReportToken) || status.ReportToken == _reportToken)
        {
            return;
        }
        _reportToken = status.ReportToken;
        Task.Run(() =>
        {
            try
            {
                var config = PilotConfigStore.Load(PilotPaths.Config);
                if (config is null)
                {
                    return;
                }
                ReportFiles.WriteRecent(PilotPaths.Journal, PilotPaths.Reports, config, Environment.MachineName);
            }
            catch (Exception ex)
            {
                CrashLog.Write(ex, notify: false);
            }
        });
    }

    private static bool IsBrowser(string? process) =>
        !string.IsNullOrEmpty(process)
        && (process.Contains("chrome", StringComparison.OrdinalIgnoreCase) || process.Contains("msedge", StringComparison.OrdinalIgnoreCase));

    private static void Paint(Border lamp, bool on, string color)
    {
        lamp.Background = new SolidColorBrush(Color.Parse(on ? color : "#D9D9D9"));
        if (lamp.Child is TextBlock label)
        {
            label.Foreground = new SolidColorBrush(on ? Colors.White : Color.Parse("#555555"));
        }
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
            CrashLog.Write(ex, notify: false);
        }
        try
        {
            PilotSetup.ApplyEmployeeLimits(static _ => { });
        }
        catch (Exception ex)
        {
            CrashLog.Write(ex, notify: false);
        }
    }
}
