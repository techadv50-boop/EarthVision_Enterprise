using System.Text.Json;

namespace WorkPilot.Core;

public static class PakistanClock
{
    private static readonly TimeZoneInfo Zone = Resolve();

    public static DateOnly Today(DateTime utc) =>
        DateOnly.FromDateTime(TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), Zone));

    public static string Key(DateOnly date) => date.ToString("yyyy-MM-dd");

    public static IReadOnlyList<DateOnly> ConnectedDays(IEnumerable<string> dayFileNames, IEnumerable<DateOnly> journalDates, int limit = 30)
    {
        var dates = new HashSet<DateOnly>();
        foreach (var name in dayFileNames)
        {
            var stem = Path.GetFileNameWithoutExtension(name);
            if (DateOnly.TryParseExact(stem, "yyyy-MM-dd", out var date))
            {
                dates.Add(date);
            }
        }
        foreach (var date in journalDates)
        {
            dates.Add(date);
        }
        return dates.OrderByDescending(date => date).Take(limit).ToList();
    }

    public static IReadOnlyList<DateOnly> LastDays(DateOnly today, int count)
    {
        var dates = new List<DateOnly>(count);
        for (var index = 0; index < count; index++)
        {
            dates.Add(today.AddDays(-index));
        }
        return dates;
    }

    private static TimeZoneInfo Resolve()
    {
        foreach (var id in new[] { "Pakistan Standard Time", "Asia/Karachi" })
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById(id);
            }
            catch (TimeZoneNotFoundException)
            {
            }
            catch (InvalidTimeZoneException)
            {
            }
        }
        return TimeZoneInfo.CreateCustomTimeZone("PKT", TimeSpan.FromHours(5), "Pakistan Standard Time", "PKT");
    }
}

public sealed class DayTotals
{
    public string Date { get; set; } = "";
    public int ActiveSeconds { get; set; }
    public int IdleSeconds { get; set; }
    public Dictionary<string, int> Programs { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public static class DayLedger
{
    public static DayTotals Load(string folder, DateOnly today)
    {
        var blank = new DayTotals { Date = PakistanClock.Key(today) };
        var path = Path.Combine(folder, blank.Date + ".json");
        if (!File.Exists(path))
        {
            return blank;
        }
        try
        {
            var totals = JsonSerializer.Deserialize<DayTotals>(File.ReadAllText(path), PilotConfigStore.Json);
            if (totals is null || !string.Equals(totals.Date, blank.Date, StringComparison.Ordinal))
            {
                return blank;
            }
            totals.Programs ??= new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            return totals;
        }
        catch (JsonException)
        {
            return blank;
        }
    }

    public static DayTotals EnsureToday(DayTotals totals, DateOnly today, out DayTotals? closed)
    {
        var key = PakistanClock.Key(today);
        if (string.Equals(totals.Date, key, StringComparison.Ordinal))
        {
            closed = null;
            return totals;
        }
        closed = string.IsNullOrEmpty(totals.Date) ? null : totals;
        return new DayTotals { Date = key };
    }

    public static void Add(DayTotals totals, bool working, int seconds, string? process)
    {
        if (seconds <= 0)
        {
            return;
        }
        totals.Programs ??= new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        if (working)
        {
            totals.ActiveSeconds += seconds;
            var name = string.IsNullOrWhiteSpace(process) ? "unknown.exe" : process;
            totals.Programs.TryGetValue(name, out var current);
            totals.Programs[name] = current + seconds;
            return;
        }
        totals.IdleSeconds += seconds;
    }

    public static void Save(string folder, DayTotals totals)
    {
        if (string.IsNullOrWhiteSpace(totals.Date))
        {
            return;
        }
        Directory.CreateDirectory(folder);
        File.WriteAllText(Path.Combine(folder, totals.Date + ".json"), JsonSerializer.Serialize(totals, PilotConfigStore.Json));
    }
}

public static class FolderAccess
{
    public static readonly string[] BuiltIn = { "Desktop", "Documents", "Downloads" };

    public static int HiddenDriveMask(IReadOnlyCollection<string> allowed, IEnumerable<char> drives)
    {
        var open = new HashSet<char>();
        foreach (var item in allowed)
        {
            if (item.Length >= 2 && item[1] == ':')
            {
                open.Add(char.ToUpperInvariant(item[0]));
            }
        }
        var mask = 0;
        foreach (var drive in drives)
        {
            var letter = char.ToUpperInvariant(drive);
            if (letter is < 'A' or > 'Z' || open.Contains(letter))
            {
                continue;
            }
            mask |= 1 << (letter - 'A');
        }
        return mask;
    }
}

public static class DayReport
{
    public static DayTotals FromSamples(DateOnly date, IReadOnlyList<ActivitySample> samples, int alarmAfterSeconds)
    {
        var totals = new DayTotals { Date = PakistanClock.Key(date) };
        var points = samples.Where(sample => PakistanClock.Today(sample.Utc) == date).OrderBy(sample => sample.Utc).ToList();
        for (var index = 0; index < points.Count - 1; index++)
        {
            var gap = (int)Math.Min(120, Math.Max(0, (points[index + 1].Utc - points[index].Utc).TotalSeconds));
            var working = ActivitySignal.IsWorking(points[index].IdleSeconds, points[index].Locked, alarmAfterSeconds);
            DayLedger.Add(totals, working, gap, points[index].Process);
        }
        return totals;
    }

    public static string Describe(DateOnly date, DayTotals totals, IReadOnlyList<ActivitySample> samples)
    {
        totals.Programs ??= new Dictionary<string, int>();
        var lines = new List<string>
        {
            date.ToString("dddd d MMMM yyyy"),
            "Active " + ReportText.FormatDuration(totals.ActiveSeconds),
            "Idle " + ReportText.FormatDuration(totals.IdleSeconds),
            "",
            "Programs"
        };
        if (totals.Programs.Count == 0)
        {
            lines.Add("No programs recorded.");
        }
        else
        {
            foreach (var program in totals.Programs.OrderByDescending(pair => pair.Value))
            {
                lines.Add(program.Key + "  " + ReportText.FormatDuration(program.Value));
            }
        }
        lines.Add("");
        lines.Add("Sites and windows");
        var titles = samples
            .Where(sample => PakistanClock.Today(sample.Utc) == date && !string.IsNullOrWhiteSpace(sample.Title))
            .Select(sample => sample.Process + " — " + sample.Title.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(40)
            .ToList();
        lines.Add(titles.Count == 0 ? "No window titles recorded." : string.Join(Environment.NewLine, titles));
        return string.Join(Environment.NewLine, lines);
    }
}
