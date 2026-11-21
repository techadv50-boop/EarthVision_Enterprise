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
    private static bool _lite;

    public static byte[]? Current(bool lite = false)
    {
        var cache = lite ? TimeSpan.FromSeconds(2) : TimeSpan.FromMilliseconds(700);
        lock (Gate)
        {
            if (_jpeg is not null && _lite == lite && DateTime.UtcNow - _taken < cache)
            {
                return _jpeg;
            }
        }
        var fresh = Capture(lite);
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
            _lite = lite;
            _taken = DateTime.UtcNow;
            return fresh;
        }
    }

    private static byte[]? Capture(bool lite)
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
            var (fitWidth, fitHeight) = ScreenFrame.Fit(width, height, lite ? 640 : 960);
            using var scaled = fitWidth == width && fitHeight == height
                ? null
                : new Bitmap(screen, new Size(fitWidth, fitHeight));
            using var stream = new MemoryStream();
            var codec = ImageCodecInfo.GetImageEncoders().First(encoder => encoder.MimeType == "image/jpeg");
            using var parameters = new EncoderParameters(1);
            parameters.Param[0] = new EncoderParameter(Encoder.Quality, lite ? 28L : 45L);
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
