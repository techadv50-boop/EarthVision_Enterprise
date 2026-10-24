using System.Diagnostics;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class ReportJob
{
    public static void Run()
    {
        var config = PilotConfigStore.Load(PilotPaths.Config);
        if (config is null)
        {
            return;
        }
        ReportFiles.WriteRecent(PilotPaths.Journal, PilotPaths.Reports, config, Environment.MachineName);
        try
        {
            Process.Start(new ProcessStartInfo("schtasks.exe", $"/Run /TN \"{PilotPaths.TrackerTask}\"")
            {
                CreateNoWindow = true,
                UseShellExecute = false
            });
        }
        catch
        {
            // The sign-in task still starts the recorder on the next login.
        }
    }
}
