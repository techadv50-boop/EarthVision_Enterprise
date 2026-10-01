namespace WorkPilot.Core;

public sealed class ActivitySample
{
    public DateTime Utc { get; init; }
    public int IdleSeconds { get; init; }
    public string Process { get; init; } = "unknown.exe";
    public string Title { get; init; } = "";
    public bool Locked { get; init; }
}

public sealed class ProgramTotal
{
    public string Process { get; set; } = "";
    public int ActiveSeconds { get; set; }
    public string Group { get; set; } = "Outside";
}

public sealed class TimelineSlice
{
    public DateTime Start { get; set; }
    public DateTime End { get; set; }
    public int Seconds { get; set; }
    public string Kind { get; set; } = "Active";
    public string Process { get; set; } = "";
    public string Title { get; set; } = "";
}

public sealed class SessionSummary
{
    public DateTime? SessionStart { get; set; }
    public DateTime? SessionEnd { get; set; }
    public int SessionSeconds { get; set; }
    public int ActiveSeconds { get; set; }
    public int IdleSeconds { get; set; }
    public int LockedSeconds { get; set; }
    public int LongestIdleSeconds { get; set; }
    public double ActivePercent { get; set; }
    public int IdleThresholdSeconds { get; set; }
    public int SampleCount { get; set; }
    public IReadOnlyList<ProgramTotal> Programs { get; set; } = Array.Empty<ProgramTotal>();
    public IReadOnlyList<ProgramTotal> OutsidePrograms { get; set; } = Array.Empty<ProgramTotal>();
    public IReadOnlyList<TimelineSlice> Timeline { get; set; } = Array.Empty<TimelineSlice>();
}

public sealed class PilotConfig
{
    public string EmployeeName { get; set; } = "Pilot Employee";
    public string UserName { get; set; } = "employee1";
    public int IdleThresholdSeconds { get; set; } = 300;
    public int AlarmAfterSeconds { get; set; } = 30;
    public int PollSeconds { get; set; } = 5;
    public int QuotaGB { get; set; } = 80;
    public string Volume { get; set; } = "C:";
    public string WorkFolder { get; set; } = @"C:\WorkPilot\employee1";
    public List<string> AllowedPrograms { get; set; } = new(PilotDefaults.AllowedPrograms);
    public List<string> SystemPrograms { get; set; } = new(PilotDefaults.SystemPrograms);
}

public sealed class LiveStatus
{
    public bool SessionOpen { get; set; }
    public bool Working { get; set; } = true;
    public int IdleSeconds { get; set; }
    public int AlarmAfterSeconds { get; set; } = 30;
    public string Program { get; set; } = "";
    public string Title { get; set; } = "";
    public int ClickCount { get; set; }
    public string EmployeeName { get; set; } = "";
    public DateTime UpdatedUtc { get; set; }
}

public static class PilotDefaults
{
    public static readonly string[] AllowedPrograms =
    {
        "chrome.exe", "msedge.exe", "WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE",
        "notepad.exe", "AcroRd32.exe", "Acrobat.exe"
    };

    public static readonly string[] SystemPrograms =
    {
        "explorer.exe", "SearchHost.exe", "StartMenuExperienceHost.exe", "ShellExperienceHost.exe",
        "TextInputHost.exe", "LockApp.exe", "LogonUI.exe", "dwm.exe", "ApplicationFrameHost.exe",
        "SystemSettings.exe", "taskmgr.exe", "sihost.exe", "PickerHost.exe", "OpenWith.exe",
        "CredentialUIBroker.exe", "UserOOBEBroker.exe"
    };

    public const int AllowDeletingBrowserHistory = 0;
    public const int IncognitoModeAvailability = 1;
    public const int BrowserGuestModeEnabled = 0;

    public static (ulong SoftBytes, ulong HardBytes) QuotaBytes(int quotaGb)
    {
        if (quotaGb < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(quotaGb));
        }
        ulong hard = (ulong)quotaGb * 1024UL * 1024UL * 1024UL;
        ulong soft = (ulong)Math.Floor(hard * 0.9);
        return (soft, hard);
    }
}
