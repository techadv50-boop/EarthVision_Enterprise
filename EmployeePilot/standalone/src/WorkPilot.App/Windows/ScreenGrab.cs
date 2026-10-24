using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class ScreenGrab
{
    private static readonly object Gate = new();
    private static byte[]? _jpeg;
    private static DateTime _taken = DateTime.MinValue;

    public static byte[]? Current()
    {
        lock (Gate)
        {
            if (_jpeg is not null && DateTime.UtcNow - _taken < TimeSpan.FromMilliseconds(280))
            {
                return _jpeg;
            }
        }
        var fresh = Capture();
        if (fresh is null)
        {
            lock (Gate)
            {
                return _jpeg;
            }
        }
        lock (Gate)
        {
            _jpeg = fresh;
            _taken = DateTime.UtcNow;
            return fresh;
        }
    }

    private static byte[]? Capture()
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }
        try
        {
            var left = GetSystemMetrics(76);
            var top = GetSystemMetrics(77);
            var width = GetSystemMetrics(78);
            var height = GetSystemMetrics(79);
            if (width < 2 || height < 2)
            {
                width = GetSystemMetrics(0);
                height = GetSystemMetrics(1);
                left = 0;
                top = 0;
            }
            if (width < 2 || height < 2)
            {
                return null;
            }
            using var screen = new Bitmap(width, height, PixelFormat.Format24bppRgb);
            using (var graphics = Graphics.FromImage(screen))
            {
                graphics.CopyFromScreen(left, top, 0, 0, new Size(width, height), CopyPixelOperation.SourceCopy);
            }
            var (fitWidth, fitHeight) = ScreenFrame.Fit(width, height, 1280);
            using var scaled = fitWidth == width && fitHeight == height
                ? null
                : new Bitmap(screen, new Size(fitWidth, fitHeight));
            using var stream = new MemoryStream();
            var codec = ImageCodecInfo.GetImageEncoders().First(encoder => encoder.MimeType == "image/jpeg");
            using var parameters = new EncoderParameters(1);
            parameters.Param[0] = new EncoderParameter(Encoder.Quality, 55L);
            (scaled ?? screen).Save(stream, codec, parameters);
            return stream.ToArray();
        }
        catch
        {
            return null;
        }
    }

    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int index);
}
