namespace WorkPilot.Windows;

public static class OfficeRepair
{
    public static void AllowOffice(string userName, Action<string> log)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }
        WindowsCommand.Run("reg.exe", "delete", @"HKLM\SOFTWARE\Policies\Microsoft\Windows\SrpV2", "/f");
        WindowsCommand.Run("reg.exe", "delete", @"HKLM\SOFTWARE\Policies\Microsoft\Windows\Safer", "/f");
        WindowsCommand.Run(
            "reg.exe", "add", @"HKLM\SYSTEM\CurrentControlSet\Services\AppIDSvc",
            "/v", "Start", "/t", "REG_DWORD", "/d", "4", "/f");
        WindowsCommand.Run(WindowsCommand.SystemTool("sc.exe"), "stop", "AppIDSvc");
        foreach (var folder in new[]
        {
            @"C:\",
            @"C:\Windows",
            @"C:\Program Files",
            @"C:\Program Files (x86)",
            @"C:\ProgramData"
        })
        {
            if (Directory.Exists(folder))
            {
                WindowsCommand.Run("icacls.exe", folder, "/remove:d", userName, "/C");
            }
        }
        foreach (var folder in OfficeFolders())
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            log("Opening " + folder + " for Word. This can take a few minutes.");
            WindowsCommand.Run("icacls.exe", 300000, folder, "/remove:d", userName, "/T", "/C");
            WindowsCommand.Run("icacls.exe", 300000, folder, "/grant", "BUILTIN\\Users:(OI)(CI)RX", userName + ":(OI)(CI)RX", "/C");
        }
        try
        {
            EmployeeDesktopLimits.ReleaseOffice(userName, log);
        }
        catch (Exception ex)
        {
            log(ex.Message);
        }
        var word = FindWord();
        if (word is null)
        {
            log("Word's program file was not found. Install Office again if Word is still missing.");
        }
        else
        {
            log("Word program: " + word);
            var officeDir = Path.GetDirectoryName(word)!;
            WindowsCommand.Run("icacls.exe", 300000, officeDir, "/remove:d", userName, "/T", "/C");
            WindowsCommand.Run("icacls.exe", 300000, officeDir, "/grant", "BUILTIN\\Users:(OI)(CI)RX", userName + ":(OI)(CI)RX", "/C");
            PlaceShortcut(word, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonDesktopDirectory), "Word.lnk"));
            var profile = Path.Combine(@"C:\Users", userName, "Desktop", "Word.lnk");
            if (Directory.Exists(Path.GetDirectoryName(profile)))
            {
                PlaceShortcut(word, profile);
            }
            log("A Word icon named Word is on the desktop. Open that icon.");
        }
        log("Restart the computer, sign in as " + userName + ", and open the Word icon on the desktop.");
    }

    private static IEnumerable<string> OfficeFolders()
    {
        yield return @"C:\Program Files\Microsoft Office";
        yield return @"C:\Program Files (x86)\Microsoft Office";
        yield return @"C:\Program Files\Common Files\Microsoft Shared";
        yield return @"C:\Program Files (x86)\Common Files\Microsoft Shared";
        yield return @"C:\ProgramData\Microsoft\Office";
        yield return @"C:\ProgramData\Microsoft\OfficeSoftwareProtectionPlatform";
    }

    private static string? FindWord()
    {
        foreach (var root in new[] { @"C:\Program Files", @"C:\Program Files (x86)" })
        {
            if (!Directory.Exists(root))
            {
                continue;
            }
            var found = FindWordUnder(root);
            if (!string.IsNullOrWhiteSpace(found))
            {
                return found;
            }
        }
        return null;
    }

    private static string? FindWordUnder(string directory)
    {
        try
        {
            foreach (var file in Directory.EnumerateFiles(directory, "WINWORD.EXE"))
            {
                return file;
            }
        }
        catch (UnauthorizedAccessException)
        {
            // This folder is locked. The Office folder may still be readable.
        }
        try
        {
            foreach (var child in Directory.EnumerateDirectories(directory))
            {
                var found = FindWordUnder(child);
                if (!string.IsNullOrWhiteSpace(found))
                {
                    return found;
                }
            }
        }
        catch (UnauthorizedAccessException)
        {
            // Skip folders the administrator account cannot list.
        }
        return null;
    }

    private static void PlaceShortcut(string target, string linkPath)
    {
        var directory = Path.GetDirectoryName(linkPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }
        var work = Path.GetDirectoryName(target) ?? target;
        var command = "$s = New-Object -ComObject WScript.Shell; "
            + $"$l = $s.CreateShortcut('{linkPath.Replace("'", "''")}'); "
            + $"$l.TargetPath = '{target.Replace("'", "''")}'; "
            + $"$l.WorkingDirectory = '{work.Replace("'", "''")}'; "
            + "$l.Description = 'Word'; $l.Save()";
        WindowsCommand.Run("powershell.exe", "-NoProfile", "-Command", command);
    }
}
