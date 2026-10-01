using System.Globalization;
using System.Net;
using System.Text;

namespace WorkPilot.Core;

public static class ReportText
{
    public static string FormatDuration(int seconds)
    {
        if (seconds < 0)
        {
            seconds = 0;
        }
        var hours = seconds / 3600;
        var minutes = (seconds % 3600) / 60;
        var remain = seconds % 60;
        if (hours > 0 && minutes == 0)
        {
            return $"{hours} h";
        }
        if (hours > 0)
        {
            return $"{hours} h {minutes} min";
        }
        if (minutes > 0 && remain == 0)
        {
            return $"{minutes} min";
        }
        if (minutes > 0)
        {
            return $"{minutes} min {remain} s";
        }
        return $"{remain} s";
    }

    public static string FormatClock(DateTime utc) =>
        utc.ToString("yyyy-MM-dd HH:mm:ss 'UTC'", CultureInfo.InvariantCulture);

    public static string ToPlainText(SessionSummary summary, string employeeName, string userName, string computerName)
    {
        var lines = new List<string>
        {
            "Work session report",
            $"Employee: {employeeName}",
            $"Windows login: {userName}",
            $"Computer: {computerName}"
        };
        if (summary.SessionStart is DateTime start && summary.SessionEnd is DateTime end)
        {
            lines.Add($"Session start: {FormatClock(start)}");
            lines.Add($"Session end: {FormatClock(end)}");
        }
        else
        {
            lines.Add("Session start: no activity recorded");
            lines.Add("Session end: no activity recorded");
        }
        lines.Add($"Session length: {FormatDuration(summary.SessionSeconds)}");
        lines.Add($"Active time: {FormatDuration(summary.ActiveSeconds)}");
        lines.Add($"Idle time: {FormatDuration(summary.IdleSeconds)}");
        lines.Add($"Locked screen (included in idle): {FormatDuration(summary.LockedSeconds)}");
        lines.Add($"Longest idle stretch: {FormatDuration(summary.LongestIdleSeconds)}");
        lines.Add($"Active percent: {summary.ActivePercent.ToString(CultureInfo.InvariantCulture)}");
        var idleMinutes = summary.IdleThresholdSeconds / 60;
        lines.Add($"Idle rule: no mouse or keyboard for {idleMinutes} min still counts the waiting period as active; after that the time is idle. A locked screen is idle immediately.");
        lines.Add("");
        lines.Add("Programs");
        if (summary.Programs.Count == 0)
        {
            lines.Add("(none)");
        }
        foreach (var program in summary.Programs)
        {
            lines.Add($"{program.Process}  {FormatDuration(program.ActiveSeconds)}  {program.Group}");
        }
        lines.Add("");
        lines.Add("Outside the allowed list");
        if (summary.OutsidePrograms.Count == 0)
        {
            lines.Add("(none)");
        }
        foreach (var program in summary.OutsidePrograms)
        {
            lines.Add($"{program.Process}  {FormatDuration(program.ActiveSeconds)}");
        }
        lines.Add("");
        lines.Add("Timeline");
        foreach (var slice in summary.Timeline)
        {
            var label = slice.Kind == "Active" ? $"{slice.Process}  {slice.Title}" : slice.Kind;
            lines.Add($"{FormatClock(slice.Start)}  {FormatDuration(slice.Seconds)}  {label}");
        }
        return string.Join("\r\n", lines);
    }

    public static string ToHtml(SessionSummary summary, string employeeName, string userName, string computerName)
    {
        var start = "No activity recorded";
        var end = "No activity recorded";
        if (summary.SessionStart is DateTime sessionStart && summary.SessionEnd is DateTime sessionEnd)
        {
            start = Encode(FormatClock(sessionStart));
            end = Encode(FormatClock(sessionEnd));
        }
        var programRows = new StringBuilder();
        if (summary.Programs.Count == 0)
        {
            programRows.AppendLine("<tr><td colspan=\"3\">No program time recorded</td></tr>");
        }
        foreach (var program in summary.Programs)
        {
            programRows.Append("<tr><td>").Append(Encode(program.Process)).Append("</td><td>")
                .Append(FormatDuration(program.ActiveSeconds)).Append("</td><td>")
                .Append(Encode(program.Group)).AppendLine("</td></tr>");
        }
        var outsideRows = new StringBuilder();
        if (summary.OutsidePrograms.Count == 0)
        {
            outsideRows.AppendLine("<tr><td colspan=\"2\">None</td></tr>");
        }
        foreach (var program in summary.OutsidePrograms)
        {
            outsideRows.Append("<tr><td>").Append(Encode(program.Process)).Append("</td><td>")
                .Append(FormatDuration(program.ActiveSeconds)).AppendLine("</td></tr>");
        }
        var timeRows = new StringBuilder();
        if (summary.Timeline.Count == 0)
        {
            timeRows.AppendLine("<tr><td colspan=\"3\">No timeline</td></tr>");
        }
        foreach (var slice in summary.Timeline)
        {
            var what = slice.Kind == "Active"
                ? $"{Encode(slice.Process)} — {Encode(slice.Title)}"
                : Encode(slice.Kind);
            timeRows.Append("<tr><td>").Append(Encode(FormatClock(slice.Start))).Append("</td><td>")
                .Append(FormatDuration(slice.Seconds)).Append("</td><td>").Append(what).AppendLine("</td></tr>");
        }
        var idleMinutes = summary.IdleThresholdSeconds / 60;
        return $$"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Work session report</title>
<style>
body { font-family: Segoe UI, sans-serif; margin: 2rem; color: #1c1c1c; }
h1 { font-size: 1.5rem; margin-bottom: 0.2rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
p.note { color: #444; max-width: 46rem; }
.cards { display: flex; flex-wrap: wrap; gap: 0.8rem; margin: 1rem 0; }
.card { border: 1px solid #ccc; padding: 0.8rem 1rem; min-width: 9rem; }
.card span { display: block; font-size: 0.8rem; color: #555; }
.card strong { font-size: 1.35rem; }
table { border-collapse: collapse; width: 100%; max-width: 56rem; }
th, td { border-bottom: 1px solid #ddd; text-align: left; padding: 0.35rem 0.5rem; vertical-align: top; }
th { background: #f4f4f4; }
</style>
</head>
<body>
<h1>Work session report</h1>
<p class="note">This report lists programs in the foreground, how long each one was used, and idle time. It does not include keystrokes, screenshots, passwords, or the clipboard.</p>
<p>Employee: <strong>{{Encode(employeeName)}}</strong><br>
Windows login: <strong>{{Encode(userName)}}</strong><br>
Computer: <strong>{{Encode(computerName)}}</strong><br>
Session start: {{start}}<br>
Session end: {{end}}</p>
<div class="cards">
<div class="card"><span>Session length</span><strong>{{FormatDuration(summary.SessionSeconds)}}</strong></div>
<div class="card"><span>Active time</span><strong>{{FormatDuration(summary.ActiveSeconds)}}</strong></div>
<div class="card"><span>Idle time</span><strong>{{FormatDuration(summary.IdleSeconds)}}</strong></div>
<div class="card"><span>Longest idle stretch</span><strong>{{FormatDuration(summary.LongestIdleSeconds)}}</strong></div>
<div class="card"><span>Active percent</span><strong>{{summary.ActivePercent.ToString(CultureInfo.InvariantCulture)}}%</strong></div>
</div>
<p class="note">Idle rule used for this report: {{idleMinutes}} minutes without mouse or keyboard. That waiting period still counts as active, so reading and short pauses are not idle. After {{idleMinutes}} minutes the time is idle. A locked screen counts as idle immediately. Locked time inside this session: {{FormatDuration(summary.LockedSeconds)}}.</p>
<h2>Programs</h2>
<table>
<thead><tr><th>Program</th><th>Active time</th><th>Allocation</th></tr></thead>
<tbody>
{{programRows}}
</tbody>
</table>
<h2>Outside the allowed list</h2>
<table>
<thead><tr><th>Program</th><th>Active time</th></tr></thead>
<tbody>
{{outsideRows}}
</tbody>
</table>
<h2>Timeline</h2>
<table>
<thead><tr><th>Start</th><th>Length</th><th>What was on screen</th></tr></thead>
<tbody>
{{timeRows}}
</tbody>
</table>
</body>
</html>
""";
    }

    private static string Encode(string? value) => WebUtility.HtmlEncode(value ?? "");
}
