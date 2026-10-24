using WorkPilot.Core;

namespace WorkPilot.Tests;

public class JournalReaderTests
{
    [Fact]
    public void RecentWorkListsTheSiteTitle()
    {
        var root = Path.Combine(Path.GetTempPath(), "workpilot-journal-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "employee1-test.jsonl"),
            """
            {"utc":"2026-10-18T13:00:00Z","idleSeconds":0,"process":"chrome.exe","title":"Inbox - Gmail","locked":false}
            {"utc":"2026-10-18T13:05:00Z","idleSeconds":0,"process":"WINWORD.EXE","title":"Daily report","locked":false}
            """);
        var text = JournalReader.Describe(root);
        Assert.Contains("chrome.exe — Inbox - Gmail", text, StringComparison.Ordinal);
        Assert.Contains("WINWORD.EXE — Daily report", text, StringComparison.Ordinal);
        Assert.Contains("Inbox - Gmail", text, StringComparison.Ordinal);
        Directory.Delete(root, true);
    }
}
