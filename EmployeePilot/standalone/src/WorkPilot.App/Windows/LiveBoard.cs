using System.Net.Http;
using System.Text.Json;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class LiveBoard
{
    private static readonly object Gate = new();
    private static LiveStatus _current = new();
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(2) };

    public static void Publish(LiveStatus status)
    {
        lock (Gate)
        {
            _current = status;
        }
        try
        {
            Directory.CreateDirectory(PilotPaths.LiveDirectory);
            File.WriteAllText(PilotPaths.LiveFile, JsonSerializer.Serialize(status, PilotConfigStore.Json));
        }
        catch
        {
            // The watch page still reads the in-memory status.
        }
    }

    public static LiveStatus ReadLocal()
    {
        lock (Gate)
        {
            return Copy(_current);
        }
    }

    public static LiveStatus ReadUrl(string url)
    {
        try
        {
            var json = Http.GetStringAsync(url).GetAwaiter().GetResult();
            var status = JsonSerializer.Deserialize<LiveStatus>(json, PilotConfigStore.Json);
            return status ?? Closed();
        }
        catch
        {
            return Closed();
        }
    }

    public static bool IsFresh(LiveStatus status) =>
        status.SessionOpen && status.UpdatedUtc > DateTime.UtcNow.AddSeconds(-15);

    private static LiveStatus Closed() => new() { SessionOpen = false, Working = true };

    private static LiveStatus Copy(LiveStatus status) => new()
    {
        SessionOpen = status.SessionOpen,
        Working = status.Working,
        IdleSeconds = status.IdleSeconds,
        AlarmAfterSeconds = status.AlarmAfterSeconds,
        Program = status.Program,
        Title = status.Title,
        ClickCount = status.ClickCount,
        EmployeeName = status.EmployeeName,
        UpdatedUtc = status.UpdatedUtc
    };
}
