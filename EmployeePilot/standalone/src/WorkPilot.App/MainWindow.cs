using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using WorkPilot.Windows;

namespace WorkPilot;

public class MainWindow : Window
{
    private readonly TextBox _fullName = new() { Text = "Pilot Employee", Watermark = "Employee full name" };
    private readonly TextBox _userName = new() { Text = "employee1", Watermark = "Windows login" };
    private readonly TextBox _password = new() { PasswordChar = '●', Watermark = "Password" };
    private readonly TextBox _confirm = new() { PasswordChar = '●', Watermark = "Type the password again" };
    private readonly TextBox _quota = new() { Text = "80", Watermark = "Disk limit in GB" };
    private readonly TextBox _idle = new() { Text = "5", Watermark = "Idle after this many minutes" };
    private readonly TextBox _log = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Height = 220 };
    private readonly Button _setup = new() { Content = "Set up this computer" };
    private readonly Button _check = new() { Content = "Check setup" };
    private readonly Button _report = new() { Content = "Open latest report" };
    private readonly Button _audit = new() { Content = "Watch programs only" };
    private readonly Button _block = new() { Content = "Block other programs" };

    public MainWindow()
    {
        Title = "Work session pilot";
        Width = 680;
        Height = 760;
        MinWidth = 560;
        MinHeight = 640;
        Content = Build();
        _setup.Click += async (_, _) => await RunBusy(_setup, SetupAsync);
        _check.Click += async (_, _) => await RunBusy(_check, CheckAsync);
        _report.Click += (_, _) => OpenReport();
        _audit.Click += async (_, _) => await RunBusy(_audit, () => RulesAsync(false));
        _block.Click += async (_, _) => await RunBusy(_block, () => RulesAsync(true));
    }

    private Control Build()
    {
        var intro = new TextBlock
        {
            Text = "One employee on this Windows 11 computer. The program creates a normal login, a disk limit, Chrome rules, and a sign-in to sign-out report. It does not record keystrokes, screenshots, or passwords.",
            TextWrapping = TextWrapping.Wrap
        };
        var buttons = new WrapPanel { Orientation = Orientation.Horizontal };
        foreach (var button in new[] { _setup, _check, _report, _audit, _block })
        {
            button.Margin = new Avalonia.Thickness(0, 0, 8, 8);
            button.MinHeight = 36;
            buttons.Children.Add(button);
        }
        var stack = new StackPanel { Spacing = 8, Margin = new Avalonia.Thickness(24) };
        stack.Children.Add(new TextBlock { Text = "Work session pilot", FontSize = 24 });
        stack.Children.Add(intro);
        stack.Children.Add(Label("Employee full name"));
        stack.Children.Add(_fullName);
        stack.Children.Add(Label("Windows login"));
        stack.Children.Add(_userName);
        stack.Children.Add(Label("Password"));
        stack.Children.Add(_password);
        stack.Children.Add(Label("Confirm password"));
        stack.Children.Add(_confirm);
        stack.Children.Add(Label("Disk space in GB"));
        stack.Children.Add(_quota);
        stack.Children.Add(Label("Minutes without mouse or keyboard before idle"));
        stack.Children.Add(_idle);
        stack.Children.Add(buttons);
        stack.Children.Add(new TextBlock { Text = "Result", FontSize = 16 });
        stack.Children.Add(new ScrollViewer { Content = _log, Height = 220 });
        return stack;
    }

    private static TextBlock Label(string text) => new() { Text = text, Margin = new Avalonia.Thickness(0, 6, 0, 0) };

    private async Task RunBusy(Button button, Func<Task> work)
    {
        var buttons = new[] { _setup, _check, _report, _audit, _block };
        foreach (var item in buttons)
        {
            item.IsEnabled = false;
        }
        try
        {
            await work();
        }
        catch (Exception ex)
        {
            Log(ex.Message);
        }
        finally
        {
            foreach (var item in buttons)
            {
                item.IsEnabled = true;
            }
            _ = button;
        }
    }

    private Task SetupAsync()
    {
        if ((_password.Text ?? "") != (_confirm.Text ?? ""))
        {
            throw new InvalidOperationException("The passwords did not match.");
        }
        if (!int.TryParse(_quota.Text, out var quota))
        {
            throw new InvalidOperationException("Enter the disk limit as a whole number of GB.");
        }
        if (!int.TryParse(_idle.Text, out var idle))
        {
            throw new InvalidOperationException("Enter the idle time as a whole number of minutes.");
        }
        var request = new PilotRequest(
            (_fullName.Text ?? "").Trim(),
            (_userName.Text ?? "").Trim(),
            _password.Text ?? "",
            quota,
            idle);
        _password.Text = "";
        _confirm.Text = "";
        return Task.Run(() => PilotSetup.Run(request, Log));
    }

    private Task CheckAsync() => Task.Run(() =>
    {
        foreach (var line in PilotSetup.Check())
        {
            Log(line);
        }
    });

    private Task RulesAsync(bool enforce) => Task.Run(() => PilotSetup.ApplyAppLocker(enforce, Log));

    private void OpenReport()
    {
        var path = Path.Combine(PilotPaths.Reports, "latest.html");
        if (!File.Exists(path))
        {
            Log("No report yet. Sign in as the employee, use the computer, then sign out and wait one minute.");
            return;
        }
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path) { UseShellExecute = true });
    }

    private void Log(string line)
    {
        Dispatcher.UIThread.Post(() =>
        {
            _log.Text = string.IsNullOrEmpty(_log.Text) ? line : _log.Text + Environment.NewLine + line;
            _log.CaretIndex = _log.Text?.Length ?? 0;
        });
    }
}
