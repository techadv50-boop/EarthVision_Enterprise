using System.Security.Principal;
using Microsoft.Win32;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class EmployeeDesktopLimits
{
    public static void Apply(string userName, string workFolder, Action<string> log)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }
        var sid = RequireSid(userName);
        var profile = ProfilePath(sid);
        var hiveName = OpenHive(sid, profile, out var loaded);
        try
        {
            using var hive = Registry.Users.OpenSubKey(hiveName, writable: true)
                ?? throw new InvalidOperationException("The employee profile did not open.");
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDrives", EmployeeDesktopPolicy.HideDriveC);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoViewOnDrive", EmployeeDesktopPolicy.HideDriveC);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoRun", 1);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "DisallowRun", 1);
            WriteString(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "SettingsPageVisibility", EmployeeDesktopPolicy.HiddenSettingsPages);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Uninstall", "NoAddRemovePrograms", 1);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\System", "DisableTaskMgr", 1);
            WriteDword(hive, @"Software\Policies\Microsoft\Windows\Installer", "DisableMSI", 2);
            WriteDword(hive, @"Software\Policies\Microsoft\Windows\Explorer", "NoUninstallFromStart", 1);
            using var blocked = hive.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\DisallowRun")
                ?? throw new InvalidOperationException("Windows did not save the blocked program list.");
            for (var index = 0; index < EmployeeDesktopPolicy.BlockedTools.Length; index++)
            {
                blocked.SetValue((index + 1).ToString(), EmployeeDesktopPolicy.BlockedTools[index], RegistryValueKind.String);
            }
        }
        finally
        {
            if (loaded)
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                var unloaded = WindowsCommand.Run("reg.exe", "unload", @"HKU\WorkPilotEmployee");
                if (unloaded.Code != 0)
                {
                    log("The employee profile was updated, but Windows kept it open. Sign the employee out and open WorkPilot again.");
                }
            }
        }
        HideSystemFolders(userName, log);
        PlaceShortcuts(profile, workFolder, log);
        log("Drive C is hidden. The employee can use Documents, Downloads, Desktop, and Control Panel.");
        log("Uninstall is blocked. The time window cannot be closed.");
        log("Sign the employee out and back in so these limits take effect.");
    }

    public static string? TrySid(string userName)
    {
        if (!OperatingSystem.IsWindows() || string.IsNullOrWhiteSpace(userName))
        {
            return null;
        }
        try
        {
            return RequireSid(userName);
        }
        catch
        {
            return null;
        }
    }

    private static string RequireSid(string userName)
    {
        foreach (var accountName in new[] { userName, Environment.MachineName + "\\" + userName })
        {
            try
            {
                var account = new NTAccount(accountName);
                return ((SecurityIdentifier)account.Translate(typeof(SecurityIdentifier))).Value;
            }
            catch (IdentityNotMappedException)
            {
                // Try the machine-qualified name next.
            }
        }
        throw new InvalidOperationException("Windows could not find the employee login " + userName + ".");
    }

    private static string ProfilePath(string sid)
    {
        using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\" + sid);
        var path = key?.GetValue("ProfileImagePath") as string;
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException("Windows could not find the employee profile folder.");
        }
        return Environment.ExpandEnvironmentVariables(path);
    }

    private static string OpenHive(string sid, string profile, out bool loaded)
    {
        using var existing = Registry.Users.OpenSubKey(sid);
        if (existing is not null)
        {
            loaded = false;
            return sid;
        }
        var database = Path.Combine(profile, "NTUSER.DAT");
        var result = WindowsCommand.Run("reg.exe", "load", @"HKU\WorkPilotEmployee", database);
        if (result.Code != 0)
        {
            WindowsCommand.Run("reg.exe", "unload", @"HKU\WorkPilotEmployee");
            result = WindowsCommand.Run("reg.exe", "load", @"HKU\WorkPilotEmployee", database);
        }
        if (result.Code != 0)
        {
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(result.Output)
                ? "Windows could not open the employee profile."
                : result.Output);
        }
        loaded = true;
        return "WorkPilotEmployee";
    }

    private static void WriteDword(RegistryKey root, string subKey, string name, int value)
    {
        using var key = root.CreateSubKey(subKey) ?? throw new InvalidOperationException("Windows did not save a folder limit.");
        key.SetValue(name, value, RegistryValueKind.DWord);
    }

    private static void WriteString(RegistryKey root, string subKey, string name, string value)
    {
        using var key = root.CreateSubKey(subKey) ?? throw new InvalidOperationException("Windows did not save a folder limit.");
        key.SetValue(name, value, RegistryValueKind.String);
    }

    private static void HideSystemFolders(string userName, Action<string> log)
    {
        foreach (var folder in new[] { @"C:\", @"C:\Windows", @"C:\Program Files", @"C:\Program Files (x86)", @"C:\ProgramData" })
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            WindowsCommand.Run("icacls.exe", folder, "/remove:d", userName);
            var denied = WindowsCommand.Run("icacls.exe", folder, "/deny", $"{userName}:(RD)");
            if (denied.Code != 0)
            {
                log($"Could not hide listing of {folder}. {denied.Output}");
            }
        }
    }

    private static void PlaceShortcuts(string profile, string workFolder, Action<string> log)
    {
        var desktop = Path.Combine(profile, "Desktop");
        if (!Directory.Exists(desktop))
        {
            var oneDrive = Path.Combine(profile, "OneDrive", "Desktop");
            desktop = Directory.Exists(oneDrive) ? oneDrive : desktop;
            Directory.CreateDirectory(desktop);
        }
        Directory.CreateDirectory(Path.Combine(profile, "Documents"));
        Directory.CreateDirectory(Path.Combine(profile, "Downloads"));
        Link(desktop, "Documents", "explorer.exe", "shell:Personal");
        Link(desktop, "Downloads", "explorer.exe", "shell:Downloads");
        Link(desktop, "Control Panel", "explorer.exe", "shell:ControlPanelFolder");
        if (!string.IsNullOrWhiteSpace(workFolder) && Directory.Exists(workFolder)
            && !workFolder.StartsWith(@"C:\", StringComparison.OrdinalIgnoreCase))
        {
            Link(desktop, "Work files", "explorer.exe", workFolder);
        }
        log("Desktop shortcuts: Documents, Downloads, and Control Panel.");
    }

    private static void Link(string desktop, string name, string target, string arguments)
    {
        var link = Path.Combine(desktop, name + ".lnk");
        var command = "$s = New-Object -ComObject WScript.Shell; "
            + $"$l = $s.CreateShortcut('{Escape(link)}'); "
            + $"$l.TargetPath = '{Escape(target)}'; "
            + $"$l.Arguments = '{Escape(arguments)}'; "
            + "$l.Save()";
        WindowsCommand.Run("powershell.exe", "-NoProfile", "-Command", command);
    }

    private static string Escape(string value) => value.Replace("'", "''");
}
