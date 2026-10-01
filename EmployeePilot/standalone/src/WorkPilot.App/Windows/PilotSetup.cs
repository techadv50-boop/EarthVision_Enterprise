using System.Diagnostics;
using System.Security;
using System.Text;
using System.Xml;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public sealed record PilotRequest(string FullName, string UserName, string Password, int QuotaGb, int IdleMinutes, int AlarmAfterSeconds);

public static class PilotSetup
{
    public const string Notice = """
Work session recording

This computer records your work session while you are signed in.

What is recorded
- The time you sign in and the time you sign out
- The program in front of you, and the window title
- Whether the mouse and keyboard are being used
- Idle time, including a locked screen

What is not recorded
- Keys you type
- Screenshots
- Passwords
- Clipboard contents
- The webcam or microphone

Chrome
- You can browse and search
- Clearing browsing history, Incognito, and Guest mode are turned off
- Page titles can appear in the session report because they are window titles

A green light means you are working. A red light means you have stopped. The computer beeps while the red light is on, until you use the mouse or keyboard again.
The administrator receives a report after you sign out.
""";

    public static void Run(PilotRequest request, Action<string> log)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new InvalidOperationException("This program sets up a Windows 11 PC. Copy WorkPilot.exe to that computer and open it there.");
        }
        Validate(request);
        var volume = SelectVolume();
        var workFolder = Path.Combine(volume + "\\", "WorkPilot", request.UserName);
        log($"Login: {request.UserName}");
        log($"Work folder: {workFolder}");
        log($"Disk limit: {request.QuotaGb} GB on {volume}");
        log($"Idle after: {request.IdleMinutes} minutes");
        log($"Red light and beep after: {request.AlarmAfterSeconds} seconds");
        if (volume == "C:")
        {
            log("The limit includes this login's Windows profile and Chrome, not only documents.");
        }

        EnsureUser(request, log);
        Directory.CreateDirectory(PilotPaths.Root);
        Directory.CreateDirectory(PilotPaths.Journal);
        Directory.CreateDirectory(PilotPaths.Reports);
        Directory.CreateDirectory(PilotPaths.Logs);
        Directory.CreateDirectory(PilotPaths.LiveDirectory);
        Directory.CreateDirectory(workFolder);
        CopyProgram(log);
        ProtectFolder(workFolder, request.UserName, modify: true);
        ProtectFolder(PilotPaths.Journal, request.UserName, modify: false);
        ProtectFolder(PilotPaths.Logs, request.UserName, modify: false);
        ProtectFolder(PilotPaths.LiveDirectory, request.UserName, modify: true);
        ProtectFolder(PilotPaths.Reports, request.UserName, modify: false, employeeAccess: false);
        File.WriteAllText(Path.Combine(workFolder, "READ-ME.txt"),
            $"Save your work in this folder.{Environment.NewLine}Your space limit on drive {volume} is {request.QuotaGb} GB.{Environment.NewLine}Recording is on while you are signed in.{Environment.NewLine}");
        File.WriteAllText(Path.Combine(PilotPaths.Root, "NOTICE.txt"), Notice);

        var config = new PilotConfig
        {
            EmployeeName = request.FullName,
            UserName = request.UserName,
            IdleThresholdSeconds = request.IdleMinutes * 60,
            AlarmAfterSeconds = request.AlarmAfterSeconds,
            PollSeconds = 5,
            QuotaGB = request.QuotaGb,
            Volume = volume,
            WorkFolder = workFolder,
            AllowedPrograms = new List<string>(PilotDefaults.AllowedPrograms),
            SystemPrograms = new List<string>(PilotDefaults.SystemPrograms)
        };
        PilotConfigStore.Save(PilotPaths.Config, config);
        ApplyQuota(volume, request.UserName, request.QuotaGb, log);
        ApplyChrome(log);
        EnableRemoteDesktop(log);
        AllowWatch(log);
        RegisterTasks(request.UserName, log);
        CreateReportShortcut(log);
        ApplyAppLocker(enforce: false, log);
        log("");
        log("Pilot is ready for one employee.");
        log("1. Sign in as " + request.UserName + " at this computer and confirm the recording message.");
        log("2. Open Chrome and confirm history cannot be cleared.");
        log("3. Sign out, wait one minute, then open Work session report on your desktop.");
        log("4. Hand over the login only after that test looks right.");
        log("Do not open Remote Desktop directly to the internet. Use a private network such as Tailscale.");
    }

    public static IReadOnlyList<string> Check()
    {
        var lines = new List<string>();
        void Add(bool ok, string name, string detail) => lines.Add((ok ? "PASS  " : "FAIL  ") + name + "  " + detail);
        var config = PilotConfigStore.Load(PilotPaths.Config);
        Add(config is not null, "Config file", PilotPaths.Config);
        if (config is null)
        {
            return lines;
        }
        var userExists = WindowsAccount.Exists(config.UserName);
        Add(userExists, "Employee login", config.UserName);
        var admins = WindowsCommand.Run(WindowsCommand.SystemTool("net.exe"), "localgroup", "Administrators");
        Add(userExists && admins.Output.IndexOf(config.UserName, StringComparison.OrdinalIgnoreCase) < 0, "Login is not an administrator", config.UserName);
        var remote = WindowsCommand.Run(WindowsCommand.SystemTool("net.exe"), "localgroup", "Remote Desktop Users");
        Add(remote.Output.IndexOf(config.UserName, StringComparison.OrdinalIgnoreCase) >= 0, "Remote Desktop allowed", config.UserName);
        Add(File.Exists(config.WorkFolder), "Work folder", config.WorkFolder);
        Add(Directory.Exists(PilotPaths.Reports), "Report folder", PilotPaths.Reports);
        Add(WindowsCommand.Run("schtasks.exe", "/Query", "/TN", PilotPaths.TrackerTask).Code == 0, "Sign-in recorder", PilotPaths.TrackerTask);
        Add(WindowsCommand.Run("schtasks.exe", "/Query", "/TN", PilotPaths.ReportTask).Code == 0, "Report task", PilotPaths.ReportTask);
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Policies\Google\Chrome");
            var history = key?.GetValue("AllowDeletingBrowserHistory");
            var incognito = key?.GetValue("IncognitoModeAvailability");
            var guest = key?.GetValue("BrowserGuestModeEnabled");
            Add(history is int h && h == 0, "Chrome history cannot be cleared", $"AllowDeletingBrowserHistory={history}");
            Add(incognito is int i && i == 1, "Chrome Incognito is off", $"IncognitoModeAvailability={incognito}");
            Add(guest is int g && g == 0, "Chrome Guest mode is off", $"BrowserGuestModeEnabled={guest}");
        }
        catch (Exception ex)
        {
            Add(false, "Chrome policy", ex.Message);
        }
        return lines;
    }

    public static void ApplyAppLocker(bool enforce, Action<string> log)
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        if (config is null)
        {
            throw new InvalidOperationException("Set up the employee before changing program rules.");
        }
        var mode = enforce ? "Enabled" : "AuditOnly";
        var rules = new StringBuilder();
        rules.AppendLine(PathRule("fd686d53-ee9b-42f8-b4a8-7c6d4f0d0c11", "Allow the Windows folder", "S-1-1-0", "%WINDIR%\\*"));
        rules.AppendLine(PathRule("b7f58856-3e0a-4a4b-9c4e-2a6d8e0f4c22", "Allow administrators", "S-1-5-32-544", "*"));
        foreach (var program in config.AllowedPrograms)
        {
            var fileName = Path.GetFileName(program);
            if (fileName.Equals("notepad.exe", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var found = FindExecutable(fileName);
            if (found is null)
            {
                log($"Not installed, so not added yet: {fileName}");
                continue;
            }
            var folder = Path.GetDirectoryName(found)! + "\\*";
            rules.AppendLine(PathRule(Guid.NewGuid().ToString(), "Allow " + fileName, "S-1-1-0", folder));
            log($"Allowed folder: {folder}");
        }
        var xml = $"""
<AppLockerPolicy Version="1">
  <RuleCollection Type="Appx" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Dll" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Exe" EnforcementMode="{mode}">
{rules}
  </RuleCollection>
  <RuleCollection Type="Msi" EnforcementMode="NotConfigured" />
  <RuleCollection Type="Script" EnforcementMode="NotConfigured" />
</AppLockerPolicy>
""";
        var policyPath = Path.Combine(PilotPaths.Root, "applocker-policy.xml");
        File.WriteAllText(policyPath, xml, Encoding.Unicode);
        WindowsCommand.Run("sc.exe", "config", "AppIDSvc", "start=", "auto");
        WindowsCommand.Run("sc.exe", "start", "AppIDSvc");
        var applied = WindowsCommand.Run(
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            $"Set-AppLockerPolicy -XmlPolicy '{policyPath}'");
        if (applied.Code != 0)
        {
            log("Program rules were not applied. The login, disk limit, Chrome rules, and recorder are still in place.");
            log(applied.Output);
            return;
        }
        log(enforce
            ? "Other programs are now blocked. Sign in as the employee and open Chrome to confirm it still starts."
            : "Program list is in audit mode. Nothing is blocked yet. Administrators can always run every program.");
    }

    private static void Validate(PilotRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.FullName))
        {
            throw new InvalidOperationException("Enter the employee name.");
        }
        if (!System.Text.RegularExpressions.Regex.IsMatch(request.UserName, "^[A-Za-z][A-Za-z0-9]{1,19}$"))
        {
            throw new InvalidOperationException("The Windows login must start with a letter and use only letters and digits, up to 20 characters.");
        }
        if (request.Password.Length < 8 || request.Password.Any(char.IsWhiteSpace)
            || !request.Password.Any(char.IsUpper) || !request.Password.Any(char.IsLower) || !request.Password.Any(char.IsDigit))
        {
            throw new InvalidOperationException("Use a password of at least 8 characters with an uppercase letter, a lowercase letter, and a digit. Do not use spaces.");
        }
        if (request.QuotaGb < 20)
        {
            throw new InvalidOperationException("Use at least 20 GB so the Windows profile and Chrome still fit.");
        }
        if (request.IdleMinutes is < 1 or > 60)
        {
            throw new InvalidOperationException("Idle minutes must be from 1 to 60.");
        }
        if (request.AlarmAfterSeconds is < 5 or > 3600)
        {
            throw new InvalidOperationException("The red light time must be from 5 to 3600 seconds.");
        }
    }

    private static void AllowWatch(Action<string> log)
    {
        WindowsCommand.Run(WindowsCommand.SystemTool("netsh.exe"), "http", "add", "urlacl", "url=http://+:8777/", "user=Everyone");
        WindowsCommand.Run(
            WindowsCommand.SystemTool("netsh.exe"),
            "advfirewall", "firewall", "add", "rule",
            "name=WorkPilot watch", "dir=in", "action=allow", "protocol=TCP", "localport=8777", "profile=any");
        log("On your computer, click Watch employee and use http://127.0.0.1:8777/status while you are testing on this PC.");
        log("From your other computer, use this PC's Tailscale address with port 8777, for example http://100.x.x.x:8777/status.");
    }

    private static string SelectVolume()
    {
        var data = DriveInfo.GetDrives()
            .Where(drive => drive.IsReady && drive.DriveType == DriveType.Fixed)
            .Where(drive => !drive.Name.StartsWith("C", StringComparison.OrdinalIgnoreCase))
            .Where(drive => string.Equals(drive.DriveFormat, "NTFS", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(drive => drive.AvailableFreeSpace)
            .FirstOrDefault();
        if (data is null)
        {
            return "C:";
        }
        return data.Name.TrimEnd('\\');
    }

    private static void EnsureUser(PilotRequest request, Action<string> log)
    {
        log("Creating the Windows login...");
        if (!WindowsAccount.Exists(request.UserName))
        {
            WindowsAccount.Create(request.UserName, request.Password, request.FullName);
            log($"Created login {request.UserName}.");
        }
        else
        {
            log($"Login {request.UserName} already exists. The password was left unchanged.");
            WindowsAccount.SetFullName(request.UserName, request.FullName);
        }
        WindowsAccount.AddToGroup(request.UserName, "Users");
        WindowsAccount.RemoveFromGroup(request.UserName, "Administrators");
        if (!WindowsAccount.TryAddToGroup(request.UserName, "Remote Desktop Users", out var remoteError))
        {
            log(remoteError);
        }
        log("Windows login is ready.");
    }

    private static void CopyProgram(Action<string> log)
    {
        var source = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(source))
        {
            throw new InvalidOperationException("WorkPilot could not find its own program file.");
        }
        var fullSource = Path.GetFullPath(source);
        var fullDest = Path.GetFullPath(PilotPaths.Exe);
        if (!string.Equals(fullSource, fullDest, StringComparison.OrdinalIgnoreCase))
        {
            File.Copy(fullSource, fullDest, true);
            log($"Copied the program to {fullDest}");
        }
    }

    private static void ProtectFolder(string path, string user, bool modify, bool employeeAccess = true)
    {
        WindowsCommand.Run("icacls.exe", path, "/inheritance:r");
        WindowsCommand.Run("icacls.exe", path, "/grant:r", "BUILTIN\\Administrators:(OI)(CI)F");
        WindowsCommand.Run("icacls.exe", path, "/grant:r", "NT AUTHORITY\\SYSTEM:(OI)(CI)F");
        if (!employeeAccess)
        {
            return;
        }
        var rights = modify ? "(OI)(CI)M" : "(OI)(CI)(RX,AD,WA)";
        WindowsCommand.Run("icacls.exe", path, "/grant:r", $"{user}:{rights}");
    }

    private static void ApplyQuota(string volume, string user, int quotaGb, Action<string> log)
    {
        var (soft, hard) = PilotDefaults.QuotaBytes(quotaGb);
        var account = Environment.MachineName + "\\" + user;
        WindowsCommand.Run("fsutil.exe", "quota", "track", volume);
        var modified = WindowsCommand.Run("fsutil.exe", "quota", "modify", volume, soft.ToString(), hard.ToString(), account);
        if (modified.Code != 0)
        {
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(modified.Output)
                ? "Disk quota could not be set."
                : modified.Output);
        }
        WindowsCommand.Run("fsutil.exe", "quota", "enforce", volume);
        log($"Disk limit is on: {quotaGb} GB for {account} on {volume}.");
    }

    private static void ApplyChrome(Action<string> log)
    {
        const string key = @"HKLM\SOFTWARE\Policies\Google\Chrome";
        RequiredReg(key, "AllowDeletingBrowserHistory", PilotDefaults.AllowDeletingBrowserHistory);
        RequiredReg(key, "IncognitoModeAvailability", PilotDefaults.IncognitoModeAvailability);
        RequiredReg(key, "BrowserGuestModeEnabled", PilotDefaults.BrowserGuestModeEnabled);
        log("Chrome policy: history cannot be cleared, Incognito is off, Guest mode is off.");
    }

    private static void RequiredReg(string key, string name, int value)
    {
        var result = WindowsCommand.Run("reg.exe", "add", key, "/v", name, "/t", "REG_DWORD", "/d", value.ToString(), "/f");
        if (result.Code != 0)
        {
            throw new InvalidOperationException(result.Output);
        }
    }

    private static void EnableRemoteDesktop(Action<string> log)
    {
        RequiredReg(@"HKLM\System\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections", 0);
        WindowsCommand.Run("netsh.exe", "advfirewall", "firewall", "set", "rule", "group=remote desktop", "new", "enable=Yes");
        log("Remote Desktop is on for this login.");
    }

    private static void RegisterTasks(string userName, Action<string> log)
    {
        var exe = PilotPaths.Exe;
        var userId = Environment.MachineName + "\\" + userName;
        var trackerXml = TaskXml(
            userId,
            "InteractiveToken",
            "LeastPrivilege",
            exe,
            "--track",
            "<LogonTrigger><Enabled>true</Enabled><UserId>" + SecurityElement.Escape(userId) + "</UserId></LogonTrigger>",
            "P7D",
            restart: true);
        var start = DateTime.Now.AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss");
        var reportXml = TaskXml(
            "S-1-5-18",
            null,
            "HighestAvailable",
            exe,
            "--report",
            $"""
            <TimeTrigger>
              <Repetition>
                <Interval>PT1M</Interval>
                <StopAtDurationEnd>false</StopAtDurationEnd>
              </Repetition>
              <StartBoundary>{start}</StartBoundary>
              <Enabled>true</Enabled>
            </TimeTrigger>
            """,
            "PT5M",
            restart: false);
        WriteTask(PilotPaths.TrackerTask, trackerXml);
        WriteTask(PilotPaths.ReportTask, reportXml);
        log("Recording starts when the employee signs in. The report updates every minute.");
    }

    private static void WriteTask(string name, string xml)
    {
        var path = Path.Combine(PilotPaths.Root, name.Replace(' ', '-') + ".xml");
        File.WriteAllText(path, xml, Encoding.Unicode);
        var result = WindowsCommand.Run("schtasks.exe", "/Create", "/TN", name, "/XML", path, "/F");
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
            ? """
              <RestartOnFailure>
                <Interval>PT1M</Interval>
                <Count>999</Count>
              </RestartOnFailure>
              """
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

    private static void CreateReportShortcut(Action<string> log)
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        var link = Path.Combine(desktop, "Work session report.lnk");
        var target = Path.Combine(PilotPaths.Reports, "latest.html");
        var command = $"$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut('{link}'); $l.TargetPath = '{target}'; $l.Description = 'Latest employee work session report'; $l.Save()";
        var result = WindowsCommand.Run("powershell.exe", "-NoProfile", "-Command", command);
        if (result.Code == 0)
        {
            log("Shortcut on your desktop: Work session report");
        }
    }

    private static string PathRule(string id, string name, string sid, string path)
    {
        return $"""
    <FilePathRule Id="{id}" Name="{SecurityElement.Escape(name)}" Description="" UserOrGroupSid="{sid}" Action="Allow">
      <Conditions><FilePathCondition Path="{SecurityElement.Escape(path)}" /></Conditions>
    </FilePathRule>
""";
    }

    private static string? FindExecutable(string fileName)
    {
        string? programFilesX86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
        var roots = new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), programFilesX86 };
        var relative = fileName.ToLowerInvariant() switch
        {
            "chrome.exe" => new[] { @"Google\Chrome\Application\chrome.exe" },
            "msedge.exe" => new[] { @"Microsoft\Edge\Application\msedge.exe" },
            "winword.exe" => new[] { @"Microsoft Office\root\Office16\WINWORD.EXE" },
            "excel.exe" => new[] { @"Microsoft Office\root\Office16\EXCEL.EXE" },
            "powerpnt.exe" => new[] { @"Microsoft Office\root\Office16\POWERPNT.EXE" },
            "acrobat.exe" => new[] { @"Adobe\Acrobat DC\Acrobat\Acrobat.exe" },
            "acrord32.exe" => new[] { @"Adobe\Acrobat Reader DC\Reader\AcroRd32.exe" },
            _ => Array.Empty<string>()
        };
        foreach (var root in roots)
        {
            if (string.IsNullOrWhiteSpace(root))
            {
                continue;
            }
            foreach (var tail in relative)
            {
                var candidate = Path.Combine(root, tail);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }
        return null;
    }
}

internal static class WindowsCommand
{
    public static string SystemTool(string name) => Path.Combine(Environment.SystemDirectory, name);

    public static (int Code, string Output) Run(string file, params string[] args)
    {
        var start = new ProcessStartInfo(file)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true
        };
        foreach (var arg in args)
        {
            start.ArgumentList.Add(arg);
        }
        using var process = Process.Start(start) ?? throw new InvalidOperationException($"Could not start {file}.");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        // Windows tools such as net.exe wait forever when input is left open.
        process.StandardInput.Close();
        if (!process.WaitForExit(60000))
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch
            {
                // The step already failed. Report that instead of the kill error.
            }
            throw new InvalidOperationException($"{Path.GetFileName(file)} did not finish within one minute.");
        }
        var output = (stdout.Result + stderr.Result).Trim();
        return (process.ExitCode, output);
    }
}
