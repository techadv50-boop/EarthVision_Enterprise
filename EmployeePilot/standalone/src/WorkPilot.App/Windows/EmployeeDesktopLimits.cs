using System.Security.Principal;
using Microsoft.Win32;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class EmployeeDesktopLimits
{
    public static void Apply(string userName, string workFolder, IReadOnlyList<string> allowedFolders, Action<string> log)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }
        var sid = RequireSid(userName);
        var profile = ProfilePath(sid);
        var hiveName = OpenHive(sid, profile, out var loaded);
        IReadOnlyDictionary<string, string> profileFolders = new Dictionary<string, string>();
        try
        {
            using var hive = Registry.Users.OpenSubKey(hiveName, writable: true)
                ?? throw new InvalidOperationException("The employee profile did not open.");
            profileFolders = ReadProfileFolders(hive, profile);
            var drives = DriveInfo.GetDrives()
                .Where(drive => drive.DriveType == DriveType.Fixed && drive.Name.Length > 0)
                .Select(drive => drive.Name[0])
                .Append('C');
            var hidden = FolderAccess.HiddenDriveMask(allowedFolders, drives);
            var view = FolderAccess.ExplorerViewMask(hidden, FolderAccess.AllowsProfileFolder(allowedFolders));
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDrives", hidden);
            WriteDword(hive, @"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoViewOnDrive", view);
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
        var allowC = allowedFolders.Any(folder => folder.StartsWith("C:", StringComparison.OrdinalIgnoreCase));
        HideSystemFolders(userName, allowC, log);
        GrantProfileFolders(userName, profileFolders, allowedFolders, log);
        PlaceShortcuts(profile, workFolder, allowedFolders, log);
        log("The employee can open: " + (allowedFolders.Count == 0 ? "nothing selected" : string.Join(", ", allowedFolders)) + ".");
        log(allowC
            ? "Drive C is open to the employee. Uninstall stays blocked."
            : "Drive C stays closed. Windows and Program Files stay closed.");
        log("Sign the employee out and back in so these folder choices take effect.");
    }

    public static void InstallStartup(string userName, string exePath, Action<string> log)
    {
        var sid = RequireSid(userName);
        var profile = ProfilePath(sid);
        var hiveName = OpenHive(sid, profile, out var loaded);
        try
        {
            using var hive = Registry.Users.OpenSubKey(hiveName, writable: true)
                ?? throw new InvalidOperationException("The employee profile did not open.");
            WriteString(hive, @"Software\Microsoft\Windows\CurrentVersion\Run", "WorkPilot", "\"" + exePath + "\" --track");
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
        var startup = Path.Combine(profile, @"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup");
        Directory.CreateDirectory(startup);
        File.WriteAllText(
            Path.Combine(startup, "WorkPilotTimer.vbs"),
            "WScript.Sleep 12000" + Environment.NewLine
            + "CreateObject(\"WScript.Shell\").Run \"\"\"" + exePath + "\"\" --track\", 1, False" + Environment.NewLine);
        log("Sign-in start saved for " + userName + ".");
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

    private static IReadOnlyDictionary<string, string> ReadProfileFolders(RegistryKey hive, string profile)
    {
        using var key = hive.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders");
        string Resolve(string name, string fallback)
        {
            var value = key?.GetValue(name) as string;
            if (string.IsNullOrWhiteSpace(value))
            {
                return fallback;
            }
            return Environment.ExpandEnvironmentVariables(value.Replace("%USERPROFILE%", profile, StringComparison.OrdinalIgnoreCase));
        }
        return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Desktop"] = Resolve("Desktop", Path.Combine(profile, "Desktop")),
            ["Documents"] = Resolve("Personal", Path.Combine(profile, "Documents")),
            ["Downloads"] = Resolve("{374DE290-123F-4565-9164-39C4925E467B}", Path.Combine(profile, "Downloads"))
        };
    }

    private static void GrantProfileFolders(string userName, IReadOnlyDictionary<string, string> profileFolders, IReadOnlyList<string> allowedFolders, Action<string> log)
    {
        var allowed = new HashSet<string>(allowedFolders, StringComparer.OrdinalIgnoreCase);
        foreach (var folder in profileFolders)
        {
            var path = folder.Value;
            if (string.IsNullOrWhiteSpace(path))
            {
                continue;
            }
            Directory.CreateDirectory(path);
            WindowsCommand.Run("icacls.exe", path, "/remove:d", userName);
            if (!allowed.Contains(folder.Key))
            {
                if (!folder.Key.Equals("Desktop", StringComparison.OrdinalIgnoreCase))
                {
                    WindowsCommand.Run("icacls.exe", path, "/deny", $"{userName}:(OI)(CI)(RD)");
                }
                continue;
            }
            var granted = WindowsCommand.Run("icacls.exe", path, "/grant:r", $"{userName}:(OI)(CI)M");
            if (granted.Code != 0)
            {
                log($"Could not open {folder.Key} for the employee. {granted.Output}");
            }
            else
            {
                log(folder.Key + " is open: " + path);
            }
        }
    }

    private static void HideSystemFolders(string userName, bool allowC, Action<string> log)
    {
        foreach (var folder in new[] { @"C:\", @"C:\Windows", @"C:\Program Files", @"C:\Program Files (x86)", @"C:\ProgramData" })
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            WindowsCommand.Run("icacls.exe", folder, "/remove:d", userName);
            if (allowC)
            {
                continue;
            }
            var denied = WindowsCommand.Run("icacls.exe", folder, "/deny", $"{userName}:(RD)");
            if (denied.Code != 0)
            {
                log($"Could not hide listing of {folder}. {denied.Output}");
            }
        }
    }

    private static void PlaceShortcuts(string profile, string workFolder, IReadOnlyList<string> allowedFolders, Action<string> log)
    {
        var desktop = Path.Combine(profile, "Desktop");
        if (!Directory.Exists(desktop))
        {
            var oneDrive = Path.Combine(profile, "OneDrive", "Desktop");
            desktop = Directory.Exists(oneDrive) ? oneDrive : desktop;
            Directory.CreateDirectory(desktop);
        }
        var allowed = new HashSet<string>(allowedFolders, StringComparer.OrdinalIgnoreCase);
        if (allowed.Contains("Documents"))
        {
            Directory.CreateDirectory(Path.Combine(profile, "Documents"));
            Link(desktop, "Documents", "explorer.exe", "shell:Personal");
        }
        if (allowed.Contains("Downloads"))
        {
            Directory.CreateDirectory(Path.Combine(profile, "Downloads"));
            Link(desktop, "Downloads", "explorer.exe", "shell:Downloads");
        }
        Link(desktop, "Control Panel", "explorer.exe", "shell:ControlPanelFolder");
        foreach (var folder in allowedFolders.Where(folder => folder.Contains('\\') || folder.Contains('/')))
        {
            if (!Directory.Exists(folder))
            {
                log("Folder is not on this computer yet: " + folder);
                continue;
            }
            Link(desktop, Path.GetFileName(folder.TrimEnd('\\', '/')), "explorer.exe", folder);
        }
        if (!string.IsNullOrWhiteSpace(workFolder) && Directory.Exists(workFolder) && allowed.Contains(workFolder))
        {
            Link(desktop, "Work files", "explorer.exe", workFolder);
        }
        log("Shortcuts were placed for the folders you allowed.");
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
