using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using WorkPilot.Windows;

namespace WorkPilot;

public class DeskWindow : Window
{
    private readonly TextBox _name = new() { Text = "Employee", Watermark = "Employee name" };
    private readonly TextBox _user = new() { Text = "employee1", Watermark = "Windows login" };
    private readonly TextBox _password = new() { Text = "WorkPilot1", Watermark = "Password" };
    private readonly TextBlock _status = new() { TextWrapping = TextWrapping.Wrap, FontSize = 16 };
    private int _busy;

    public DeskWindow()
    {
        Title = "DeskWatch";
        Width = 760;
        Height = 640;
        MinWidth = 640;
        MinHeight = 480;
        Background = new SolidColorBrush(Color.Parse("#F3F6F4"));
        Content = Build();
    }

    private Control Build()
    {
        var setup = new Button { Content = "Set up this computer", MinHeight = 44, HorizontalAlignment = HorizontalAlignment.Left };
        setup.Click += async (_, _) =>
        {
            if (Interlocked.Exchange(ref _busy, 1) == 1)
            {
                return;
            }
            setup.IsEnabled = false;
            _status.Text = "Working. Word, Excel, and PowerPoint stay allowed.";
            try
            {
                var fullName = _name.Text?.Trim() ?? "";
                var userName = _user.Text?.Trim() ?? "";
                var password = _password.Text ?? "";
                if (fullName.Length == 0 || userName.Length == 0 || password.Length == 0)
                {
                    throw new InvalidOperationException("Enter the employee name, login, and password.");
                }
                var lines = await Task.Run(() =>
                {
                    var log = new List<string>();
                    DeskSetup.Run(fullName, userName, password, line => log.Add(line));
                    return string.Join(Environment.NewLine, log);
                });
                _status.Text = lines;
            }
            catch (Exception ex)
            {
                CrashLog.Write(ex, notify: false);
                _status.Text = ex.Message;
            }
            finally
            {
                setup.IsEnabled = true;
                Interlocked.Exchange(ref _busy, 0);
            }
        };
        var page = new StackPanel { Margin = new Avalonia.Thickness(28), Spacing = 12 };
        page.Children.Add(new TextBlock
        {
            Text = "DeskWatch",
            FontSize = 28,
            FontWeight = FontWeight.SemiBold
        });
        page.Children.Add(new TextBlock
        {
            Text = "This is the activity timer and the live screen on port 8777. It does not block Word, Excel, or PowerPoint, and it removes the old block that stopped Office for the employee.",
            TextWrapping = TextWrapping.Wrap,
            FontSize = 16
        });
        page.Children.Add(Label("Employee name"));
        page.Children.Add(_name);
        page.Children.Add(Label("Windows login"));
        page.Children.Add(_user);
        page.Children.Add(Label("Password"));
        page.Children.Add(_password);
        page.Children.Add(setup);
        page.Children.Add(_status);
        return new ScrollViewer { Content = page };
    }

    private static TextBlock Label(string text) => new() { Text = text, FontSize = 16 };
}
