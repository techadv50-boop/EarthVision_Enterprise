using System.Runtime.InteropServices;

namespace WorkPilot.Windows;

public static class SystemBeep
{
    public static void Tone()
    {
        try
        {
            KeepAudible();
            _ = waveOutSetVolume(IntPtr.Zero, 0xFFFFFFFF);
            _ = Beep(880, 280);
        }
        catch
        {
            // A PC with no beep device still shows the red light.
        }
    }

    private static void KeepAudible()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }
        var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        enumerator.GetDefaultAudioEndpoint(0, 1, out var device);
        var iid = typeof(IAudioEndpointVolume).GUID;
        device.Activate(ref iid, 23, IntPtr.Zero, out var raw);
        var volume = (IAudioEndpointVolume)raw;
        var context = Guid.Empty;
        volume.SetMute(false, ref context);
        volume.GetMasterVolumeLevelScalar(out var level);
        if (level < 0.45f)
        {
            volume.SetMasterVolumeLevelScalar(0.45f, ref context);
        }
    }

    [DllImport("kernel32.dll", EntryPoint = "Beep")]
    private static extern bool Beep(uint frequency, uint duration);

    [DllImport("winmm.dll")]
    private static extern int waveOutSetVolume(IntPtr device, uint volume);

    [ComImport]
    [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumerator
    {
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
        [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object instance);
    }

    [ComImport]
    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume
    {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr client);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr client);
        [PreserveSig] int GetChannelCount(out uint count);
        [PreserveSig] int SetMasterVolumeLevel(float level, ref Guid context);
        [PreserveSig] int SetMasterVolumeLevelScalar(float level, ref Guid context);
        [PreserveSig] int GetMasterVolumeLevel(out float level);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
        [PreserveSig] int SetChannelVolumeLevel(uint channel, float level, ref Guid context);
        [PreserveSig] int SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
        [PreserveSig] int GetChannelVolumeLevel(uint channel, out float level);
        [PreserveSig] int GetChannelVolumeLevelScalar(uint channel, out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }
}
