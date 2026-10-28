using WorkPilot.Core;

namespace WorkPilot.Tests;

public class ReportTests
{
    [Fact]
    public void ChromePoliciesBlockHistoryAndPrivateWindows()
    {
        Assert.Equal(0, PilotDefaults.AllowDeletingBrowserHistory);
        Assert.Equal(1, PilotDefaults.IncognitoModeAvailability);
        Assert.Equal(0, PilotDefaults.BrowserGuestModeEnabled);
    }

    [Fact]
    public void QuotaBytesMatchEightyGigabytes()
    {
        var (soft, hard) = PilotDefaults.QuotaBytes(80);
        Assert.Equal(80UL * 1024UL * 1024UL * 1024UL, hard);
        Assert.Equal((ulong)Math.Floor(hard * 0.9), soft);
    }

    [Fact]
    public void EmptySessionIsZero()
    {
        var summary = SessionAnalyzer.Summarize(Array.Empty<ActivitySample>(), 300);
        Assert.Equal(0, summary.SessionSeconds);
        Assert.Equal(0, summary.ActiveSeconds);
    }

    [Fact]
    public void ContinuousInputStaysActive()
    {
        var samples = EveryMinute(0, 40, "2026-09-30T09:", "chrome.exe", "Inbox");
        var summary = SessionAnalyzer.Summarize(samples, 300, new[] { "chrome.exe" });
        Assert.Equal(40 * 60, summary.SessionSeconds);
        Assert.Equal(40 * 60, summary.ActiveSeconds);
        Assert.Equal(0, summary.IdleSeconds);
        Assert.Equal(40 * 60, summary.Programs[0].ActiveSeconds);
        Assert.Equal("Allowed", summary.Programs[0].Group);
        Assert.Empty(summary.OutsidePrograms);
        Assert.Single(summary.Timeline);
    }

    [Fact]
    public void FiveMinuteGapAfterTypingBecomesTenMinutesIdle()
    {
        var samples = new List<ActivitySample>();
        for (var minute = 0; minute <= 40; minute++)
        {
            var idle = minute > 10 && minute < 25 ? (minute - 10) * 60 : 0;
            var process = minute >= 25 ? "WINWORD.EXE" : "chrome.exe";
            var title = minute >= 25 ? "Report.docx" : "Inbox";
            samples.Add(Sample($"2026-09-30T09:{minute:00}:00Z", idle, process, title));
        }
        var summary = SessionAnalyzer.Summarize(samples, 300, new[] { "chrome.exe", "WINWORD.EXE" });
        Assert.Equal(40 * 60, summary.SessionSeconds);
        Assert.Equal(30 * 60, summary.ActiveSeconds);
        Assert.Equal(10 * 60, summary.IdleSeconds);
        Assert.Equal(10 * 60, summary.LongestIdleSeconds);
        Assert.Equal(75, summary.ActivePercent);
    }

    [Fact]
    public void ShortGapUnderThresholdStaysActive()
    {
        var summary = SessionAnalyzer.Summarize(new[]
        {
            Sample("2026-09-30T10:00:00Z", 0, "EXCEL.EXE", "Sheet"),
            Sample("2026-09-30T10:04:00Z", 0, "EXCEL.EXE", "Sheet")
        }, 300, new[] { "EXCEL.EXE" });
        Assert.Equal(4 * 60, summary.ActiveSeconds);
        Assert.Equal(0, summary.IdleSeconds);
    }

    [Fact]
    public void IdleStartsExactlyAtTheThreshold()
    {
        var summary = SessionAnalyzer.Summarize(new[]
        {
            Sample("2026-09-30T11:00:00Z", 0, "chrome.exe", "Search"),
            Sample("2026-09-30T11:10:00Z", 600, "chrome.exe", "Search")
        }, 300, new[] { "chrome.exe" });
        Assert.Equal(300, summary.ActiveSeconds);
        Assert.Equal(300, summary.IdleSeconds);
    }

    [Fact]
    public void UnknownProgramIsOutsideTheAllocation()
    {
        var summary = SessionAnalyzer.Summarize(EveryMinute(0, 10, "2026-09-30T12:", "game.exe", "Level 1"), 300, new[] { "chrome.exe" }, new[] { "explorer.exe" });
        Assert.Equal("Outside", summary.Programs[0].Group);
        Assert.Equal(10 * 60, summary.OutsidePrograms[0].ActiveSeconds);
    }

    [Fact]
    public void WindowsShellIsNotAViolation()
    {
        var summary = SessionAnalyzer.Summarize(new[]
        {
            Sample("2026-09-30T13:00:00Z", 0, "explorer.exe", "File Explorer"),
            Sample("2026-09-30T13:03:00Z", 0, "explorer.exe", "File Explorer")
        }, 300, new[] { "chrome.exe" }, new[] { "explorer.exe" });
        Assert.Equal("Windows", summary.Programs[0].Group);
        Assert.Empty(summary.OutsidePrograms);
    }

    [Fact]
    public void LockedScreenIsIdleImmediately()
    {
        var summary = SessionAnalyzer.Summarize(new[]
        {
            Sample("2026-09-30T14:00:00Z", 0, "chrome.exe", "Mail", false),
            Sample("2026-09-30T14:02:00Z", 0, "LockApp.exe", "Windows Default Lock Screen", true),
            Sample("2026-09-30T14:12:00Z", 600, "LockApp.exe", "Windows Default Lock Screen", true)
        }, 300, new[] { "chrome.exe" }, new[] { "LockApp.exe" });
        Assert.Equal(2 * 60, summary.ActiveSeconds);
        Assert.Equal(10 * 60, summary.IdleSeconds);
        Assert.Equal(10 * 60, summary.LockedSeconds);
    }

    [Fact]
    public void SamplesOutOfOrderFollowTheClock()
    {
        var summary = SessionAnalyzer.Summarize(new[]
        {
            Sample("2026-09-30T15:05:00Z", 0, "notepad.exe", "Notes"),
            Sample("2026-09-30T15:00:00Z", 0, "notepad.exe", "Notes")
        }, 300, new[] { "notepad.exe" });
        Assert.Equal(5 * 60, summary.ActiveSeconds);
    }

    [Fact]
    public void HtmlEscapesTheEmployeeNameAndShowsActiveTime()
    {
        var samples = new List<ActivitySample>();
        for (var minute = 0; minute <= 40; minute++)
        {
            var idle = minute > 10 && minute < 25 ? (minute - 10) * 60 : 0;
            var process = minute >= 25 ? "WINWORD.EXE" : "chrome.exe";
            samples.Add(Sample($"2026-09-30T09:{minute:00}:00Z", idle, process, "Inbox"));
        }
        var summary = SessionAnalyzer.Summarize(samples, 300, new[] { "chrome.exe", "WINWORD.EXE" });
        var html = ReportText.ToHtml(summary, "Pilot <Employee>", "employee1", "DESKTOP-ENCM4H4");
        Assert.Contains("Pilot &lt;Employee&gt;", html, StringComparison.Ordinal);
        Assert.Contains("30 min", html, StringComparison.Ordinal);
        Assert.DoesNotContain("<script>", html, StringComparison.Ordinal);
        var text = ReportText.ToPlainText(summary, "Pilot Employee", "employee1", "DESKTOP-ENCM4H4");
        Assert.Contains("Longest idle stretch: 10 min", text, StringComparison.Ordinal);
    }

    [Fact]
    public void JournalFileBecomesAReport()
    {
        var root = Path.Combine(Path.GetTempPath(), "workpilot-tests-" + Guid.NewGuid().ToString("N"));
        var journal = Path.Combine(root, "journal");
        var reports = Path.Combine(root, "Reports");
        Directory.CreateDirectory(journal);
        var lines = new List<string>();
        for (var minute = 0; minute <= 10; minute++)
        {
            lines.Add($$"""{"utc":"2026-09-30T16:{{minute:00}}:00Z","idleSeconds":0,"process":"chrome.exe","title":"Search","locked":false}""");
        }
        File.WriteAllLines(Path.Combine(journal, "employee1-test.jsonl"), lines);
        var config = new PilotConfig
        {
            EmployeeName = "Pilot Employee",
            UserName = "employee1",
            IdleThresholdSeconds = 300,
            AllowedPrograms = new List<string> { "chrome.exe" },
            SystemPrograms = new List<string>()
        };
        var count = ReportFiles.WriteRecent(journal, reports, config, "DESKTOP-ENCM4H4", DateTime.UtcNow.AddDays(-1));
        Assert.Equal(1, count);
        var html = File.ReadAllText(Path.Combine(reports, "latest.html"));
        Assert.Contains("10 min", html, StringComparison.Ordinal);
        Assert.Contains("chrome.exe", html, StringComparison.Ordinal);
        Directory.Delete(root, true);
    }

    private static List<ActivitySample> EveryMinute(int from, int to, string prefix, string process, string title)
    {
        var samples = new List<ActivitySample>();
        for (var minute = from; minute <= to; minute++)
        {
            samples.Add(Sample($"{prefix}{minute:00}:00Z", 0, process, title));
        }
        return samples;
    }

    private static ActivitySample Sample(string iso, int idle, string process, string title, bool locked = false) =>
        new()
        {
            Utc = DateTime.Parse(iso, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.AdjustToUniversal | System.Globalization.DateTimeStyles.AssumeUniversal),
            IdleSeconds = idle,
            Process = process,
            Title = title,
            Locked = locked
        };
}
