using System.Runtime.InteropServices;

namespace WorkPilot.Windows;

public static class SystemBeep
{
    public static void Tone()
    {
        try
        {
            _ = Beep(880, 280);
        }
        catch
        {
            // A PC with no beep device still shows the red light.
        }
    }

    [DllImport("kernel32.dll", EntryPoint = "Beep")]
    private static extern bool Beep(uint frequency, uint duration);
}
