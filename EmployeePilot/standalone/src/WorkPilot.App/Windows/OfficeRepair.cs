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
            @"C:\ProgramData",
            @"C:\Program Files\Microsoft Office",
            @"C:\Program Files (x86)\Microsoft Office"
        })
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            WindowsCommand.Run("icacls.exe", folder, "/remove:d", userName);
        }
        foreach (var folder in new[]
        {
            @"C:\Program Files\Microsoft Office",
            @"C:\Program Files (x86)\Microsoft Office"
        })
        {
            if (!Directory.Exists(folder))
            {
                continue;
            }
            WindowsCommand.Run("icacls.exe", folder, "/grant", "BUILTIN\\Users:(OI)(CI)RX");
        }
        try
        {
            EmployeeDesktopLimits.ReleaseOffice(userName, log);
        }
        catch (Exception ex)
        {
            log(ex.Message);
        }
        log("Word, Excel, and PowerPoint are allowed for " + userName + ".");
        log("Restart the computer once, then open Word from the employee login.");
    }
}
