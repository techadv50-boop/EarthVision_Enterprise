using System.Globalization;
using System.Text.Json;

namespace WorkPilot.Core;

public static class ReportFiles
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public static int WriteRecent(string journalFolder, string reportsFolder, PilotConfig config, string computerName, DateTime? newerThanUtc = null)
    {
        if (!Directory.Exists(journalFolder))
        {
            return 0;
        }
        Directory.CreateDirectory(reportsFolder);
        var cutoff = newerThanUtc ?? DateTime.UtcNow.AddDays(-2);
        var files = new DirectoryInfo(journalFolder)
            .GetFiles("*.jsonl")
            .Where(file => file.LastWriteTimeUtc >= cutoff)
            .OrderBy(file => file.LastWriteTimeUtc)
            .ToList();
        string? latestHtml = null;
        foreach (var file in files)
        {
            var samples = ReadSamples(file.FullName);
            var summary = SessionAnalyzer.Summarize(samples, config.IdleThresholdSeconds, config.AllowedPrograms, config.SystemPrograms);
            var baseName = Path.GetFileNameWithoutExtension(file.Name);
            var htmlPath = Path.Combine(reportsFolder, baseName + ".html");
            var textPath = Path.Combine(reportsFolder, baseName + ".txt");
            File.WriteAllText(htmlPath, ReportText.ToHtml(summary, config.EmployeeName, config.UserName, computerName));
            File.WriteAllText(textPath, ReportText.ToPlainText(summary, config.EmployeeName, config.UserName, computerName));
            latestHtml = htmlPath;
        }
        if (latestHtml is not null)
        {
            File.Copy(latestHtml, Path.Combine(reportsFolder, "latest.html"), true);
            File.Copy(Path.ChangeExtension(latestHtml, ".txt"), Path.Combine(reportsFolder, "latest.txt"), true);
        }
        return files.Count;
    }

    public static List<ActivitySample> ReadSamples(string jsonlPath)
    {
        var samples = new List<ActivitySample>();
        foreach (var line in File.ReadLines(jsonlPath))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }
            try
            {
                var row = JsonSerializer.Deserialize<JournalRow>(line, JsonOptions);
                if (row?.Utc is null)
                {
                    continue;
                }
                var utc = DateTime.Parse(row.Utc, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
                samples.Add(new ActivitySample
                {
                    Utc = utc,
                    IdleSeconds = row.IdleSeconds,
                    Process = row.Process ?? "unknown.exe",
                    Title = row.Title ?? "",
                    Locked = row.Locked
                });
            }
            catch (JsonException)
            {
                continue;
            }
            catch (FormatException)
            {
                continue;
            }
        }
        return samples;
    }

    private sealed class JournalRow
    {
        public string? Utc { get; set; }
        public int IdleSeconds { get; set; }
        public string? Process { get; set; }
        public string? Title { get; set; }
        public bool Locked { get; set; }
    }
}
