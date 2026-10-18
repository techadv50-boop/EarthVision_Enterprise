using System.Text.Json;

namespace WorkPilot.Core;

public static class JournalReader
{
    public static string Describe(string journalDirectory)
    {
        if (!Directory.Exists(journalDirectory))
        {
            return "No activity yet. Sign in as the employee and use this computer.";
        }
        var rows = new List<Row>();
        foreach (var file in Directory.GetFiles(journalDirectory, "*.jsonl").OrderByDescending(File.GetLastWriteTimeUtc).Take(3))
        {
            foreach (var line in File.ReadLines(file))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }
                try
                {
                    var row = JsonSerializer.Deserialize<Row>(line, PilotConfigStore.Json);
                    if (row is not null && row.Utc != default)
                    {
                        rows.Add(row);
                    }
                }
                catch (JsonException)
                {
                    // Skip a damaged line and keep the rest of the log.
                }
            }
        }
        if (rows.Count == 0)
        {
            return "No activity yet. Sign in as the employee and use this computer.";
        }
        rows.Sort((left, right) => left.Utc.CompareTo(right.Utc));
        var recent = rows.TakeLast(40).ToList();
        var lines = new List<string> { "Recent work" };
        foreach (var row in recent)
        {
            var when = row.Utc.ToLocalTime().ToString("HH:mm:ss");
            var title = string.IsNullOrWhiteSpace(row.Title) ? "" : " — " + row.Title.Trim();
            lines.Add($"{when}  {row.Process}{title}");
        }
        lines.Add("");
        lines.Add("Sites");
        var sites = recent
            .Where(row => IsBrowser(row.Process) && !string.IsNullOrWhiteSpace(row.Title))
            .Select(row => row.Title.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        lines.Add(sites.Count == 0 ? "(none yet)" : string.Join(Environment.NewLine, sites));
        return string.Join(Environment.NewLine, lines);
    }

    private static bool IsBrowser(string process) =>
        process.Contains("chrome", StringComparison.OrdinalIgnoreCase)
        || process.Contains("msedge", StringComparison.OrdinalIgnoreCase)
        || process.Contains("firefox", StringComparison.OrdinalIgnoreCase);

    private sealed class Row
    {
        public DateTime Utc { get; set; }
        public string Process { get; set; } = "";
        public string Title { get; set; } = "";
    }
}
