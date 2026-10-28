using System.Security;
using System.Text;
using WorkPilot.Core;
using WorkPilot.Windows;

namespace WorkPilot;

public static class DeskSetup
{
    public const string Root = @"C:\ProgramData\DeskWatch";
    public static string Exe => Path.Combine(Root, "DeskWatch.exe");

    public static void Run(string fullName, string userName, string password, Action<string> log)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new InvalidOperationException("DeskWatch setup runs on Windows.");
        }
        if (!WindowsAccount.Exists(userName))
        {
            WindowsAccount.Create(userName, password, fullName);
            log("Created login " + userName + ".");
        }
        else
        {
            WindowsAccount.SetFullName(userName, fullName);
            log("Login " + userName + " already exists. The password was left unchanged.");
        }
        WindowsAccount.AddToGroup(userName, "Users");
        try
        {
            WindowsAccount.RemoveFromGroup(userName, "Administrators");
        }
        catch (InvalidOperationException ex)
        {
            log(ex.Message);
        }
        if (!WindowsAccount.TryAddToGroup(userName, "Remote Desktop Users", out var remoteError) && remoteError.Length > 0)
        {
            log(remoteError);
        }
        WindowsCommand.Run("reg.exe", "add", @"HKLM\System\CurrentControlSet\Control\Terminal Server", "/v", "fDenyTSConnections", "/t", "REG_DWORD", "/d", "0", "/f");
        WindowsCommand.Run(WindowsCommand.SystemTool("netsh.exe"), "advfirewall", "firewall", "set", "rule", "group=remote desktop", "new", "enable=Yes");
        WindowsCommand.Run(WindowsCommand.SystemTool("netsh.exe"), "http", "add", "urlacl", "url=http://+:8777/", "user=Everyone");
        WindowsCommand.Run(
            WindowsCommand.SystemTool("netsh.exe"),
            "advfirewall", "firewall", "add", "rule",
            "name=DeskWatch watch", "dir=in", "action=allow", "protocol=TCP", "localport=8777", "profile=any");
        log("Remote Desktop is on. The live page uses port 8777.");

        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(PilotPaths.Root);
        Directory.CreateDirectory(PilotPaths.Journal);
        Directory.CreateDirectory(PilotPaths.Reports);
        Directory.CreateDirectory(PilotPaths.Logs);
        Directory.CreateDirectory(PilotPaths.LiveDirectory);
        Directory.CreateDirectory(PilotPaths.Days);
        var config = PilotConfigStore.Load(PilotPaths.Config) ?? new PilotConfig();
        config.EmployeeName = fullName;
        config.UserName = userName;
        if (string.IsNullOrWhiteSpace(config.WorkFolder))
        {
            config.WorkFolder = Path.Combine(@"C:\WorkPilot", userName);
        }
        PilotConfigStore.Save(PilotPaths.Config, config);

        var source = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(source))
        {
            throw new InvalidOperationException("DeskWatch could not find its own program file.");
        }
        var installed = Exe;
        if (!string.Equals(Path.GetFullPath(source), Path.GetFullPath(installed), StringComparison.OrdinalIgnoreCase))
        {
            File.Copy(source, installed, true);
            log("Copied the program to " + installed);
        }
        OfficeRepair.AllowOffice(userName, log);
        EmployeeDesktopLimits.InstallStartup(userName, installed, log);
        RegisterTasks(userName, installed, log);
        var started = WindowsCommand.Run(WindowsCommand.SystemTool("schtasks.exe"), "/Run", "/TN", PilotPaths.TrackerTask);
        if (started.Code != 0)
        {
            log("The employee is not signed in yet. The timer starts at the next employee sign-in.");
        }
        log("Restart the computer. Sign in as " + userName + " and open Word.");
        log("The timer sits in a corner of the employee desktop.");
        log("From your other computer, open http:// and the Tailscale address that starts with 100, then :8777/");
    }

    private static void RegisterTasks(string userName, string exe, Action<string> log)
    {
        var userId = Environment.MachineName + "\\" + userName;
        WriteTask(PilotPaths.TrackerTask, TaskXml(userId, "InteractiveToken", "LeastPrivilege", exe, "--track",
            "<LogonTrigger><Enabled>true</Enabled><Delay>PT15S</Delay><UserId>" + SecurityElement.Escape(userId) + "</UserId></LogonTrigger>",
            "P7D", restart: true));
        var start = DateTime.Now.AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss");
        WriteTask(PilotPaths.ReportTask, TaskXml("S-1-5-18", null, "HighestAvailable", exe, "--report",
            "<TimeTrigger><Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>" + start + "</StartBoundary><Enabled>true</Enabled></TimeTrigger>",
            "PT5M", restart: false));
        log("The timer starts when " + userName + " signs in.");
    }

    private static void WriteTask(string name, string xml)
    {
        var path = Path.Combine(Root, name.Replace(' ', '-') + ".xml");
        File.WriteAllText(path, xml, Encoding.Unicode);
        var result = WindowsCommand.Run(WindowsCommand.SystemTool("schtasks.exe"), "/Create", "/TN", name, "/XML", path, "/F");
        if (result.Code != 0)
        {
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(result.Output)
                ? "Windows could not create the scheduled task " + name + "."
                : result.Output);
        }
    }

    private static string TaskXml(string userId, string? logonType, string runLevel, string command, string arguments, string triggers, string limit, bool restart)
    {
        var logon = logonType is null ? "" : $"<LogonType>{logonType}</LogonType>";
        var restartXml = restart
            ? "<RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>"
            : "";
        return $"""
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    {triggers}
  </Triggers>
  <Principals>
    <Principal>
      <UserId>{SecurityElement.Escape(userId)}</UserId>
      {logon}
      <RunLevel>{runLevel}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>{limit}</ExecutionTimeLimit>
    {restartXml}
  </Settings>
  <Actions>
    <Exec>
      <Command>{SecurityElement.Escape(command)}</Command>
      <Arguments>{SecurityElement.Escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
""";
    }
}
