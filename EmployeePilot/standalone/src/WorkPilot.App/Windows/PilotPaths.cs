namespace WorkPilot.Windows;

public static class PilotPaths
{
    public const string Root = @"C:\ProgramData\WorkPilot";
    public static string Config => Path.Combine(Root, "pilot.json");
    public static string Journal => Path.Combine(Root, "journal");
    public static string Reports => Path.Combine(Root, "Reports");
    public static string Logs => Path.Combine(Root, "logs");
    public static string Exe => Path.Combine(Root, "WorkPilot.exe");
    public const string TrackerTask = "WorkPilot Session Tracker";
    public const string ReportTask = "WorkPilot Session Report";
}
