using WorkPilot.Core;

namespace WorkPilot.Tests;

public class ActivitySignalTests
{
    [Fact]
    public void RecentInputStaysGreen()
    {
        Assert.True(ActivitySignal.IsWorking(0, locked: false, alarmAfterSeconds: 30));
        Assert.True(ActivitySignal.IsWorking(29, locked: false, alarmAfterSeconds: 30));
    }

    [Fact]
    public void IdleAtTheChosenTimeTurnsRed()
    {
        Assert.False(ActivitySignal.IsWorking(30, locked: false, alarmAfterSeconds: 30));
        Assert.False(ActivitySignal.IsWorking(90, locked: false, alarmAfterSeconds: 30));
    }

    [Fact]
    public void LockedScreenTurnsRedImmediately()
    {
        Assert.False(ActivitySignal.IsWorking(0, locked: true, alarmAfterSeconds: 30));
    }

    [Fact]
    public void SessionClockAddsWorkingTimeToActiveAndStoppedTimeToIdle()
    {
        var active = 0;
        var idle = 0;
        SessionClock.Add(ref active, ref idle, working: true, elapsedSeconds: 12);
        SessionClock.Add(ref active, ref idle, working: false, elapsedSeconds: 5);
        SessionClock.Add(ref active, ref idle, working: true, elapsedSeconds: 0);
        Assert.Equal(12, active);
        Assert.Equal(5, idle);
    }

    [Fact]
    public void DriveCIsTheThirdDriveBit()
    {
        Assert.Equal(4, EmployeeDesktopPolicy.HideDriveC);
        Assert.Contains("cmd.exe", EmployeeDesktopPolicy.BlockedTools);
        Assert.Contains("appsfeatures", EmployeeDesktopPolicy.HiddenSettingsPages);
    }

    [Fact]
    public void StopFreezesTheTimerAndResetStartsANewOne()
    {
        var clock = new TimerControl();
        clock.Tick(sessionConnected: true, command: "stop");
        Assert.False(clock.Running);
        Assert.True(clock.ReportDue);
        clock.Tick(sessionConnected: true, command: null);
        Assert.False(clock.Running);
        Assert.False(clock.ReportDue);
        clock.Tick(sessionConnected: true, command: "reset");
        Assert.True(clock.Running);
        Assert.True(clock.BeginSession);
        Assert.True(clock.ReportDue);
    }

    [Fact]
    public void DisconnectStopsTheTimerAndReconnectStartsAnother()
    {
        var clock = new TimerControl();
        clock.Tick(sessionConnected: false, command: null);
        Assert.False(clock.Running);
        Assert.True(clock.ReportDue);
        Assert.Contains("disconnected", clock.Note, StringComparison.OrdinalIgnoreCase);
        clock.Tick(sessionConnected: false, command: null);
        Assert.False(clock.ReportDue);
        clock.Tick(sessionConnected: true, command: null);
        Assert.True(clock.Running);
        Assert.True(clock.BeginSession);
        Assert.False(clock.ReportDue);
    }

    [Fact]
    public void TimerCommandRoundTrip()
    {
        var issued = new DateTime(2026, 10, 20, 1, 43, 0, DateTimeKind.Utc);
        Assert.True(TimerCommand.TryParse(TimerCommand.Format("stop", issued), out var action, out var parsed));
        Assert.Equal("stop", action);
        Assert.Equal(issued, parsed.ToUniversalTime());
        Assert.False(TimerCommand.TryParse("close|now", out _, out _));
    }

    [Fact]
    public void PakistanMidnightSplitsTheWorkDay()
    {
        var beforeMidnight = new DateTime(2026, 10, 19, 18, 30, 0, DateTimeKind.Utc);
        var afterMidnight = new DateTime(2026, 10, 19, 19, 30, 0, DateTimeKind.Utc);
        Assert.Equal(new DateOnly(2026, 10, 19), PakistanClock.Today(beforeMidnight));
        Assert.Equal(new DateOnly(2026, 10, 20), PakistanClock.Today(afterMidnight));
    }

    [Fact]
    public void SamePakistanDateKeepsAddingAndTheNextDateStartsAtZero()
    {
        var today = new DateOnly(2026, 10, 20);
        var totals = new DayTotals { Date = "2026-10-20", ActiveSeconds = 40, IdleSeconds = 5 };
        totals = DayLedger.EnsureToday(totals, today, out var closed);
        Assert.Null(closed);
        DayLedger.Add(totals, working: true, seconds: 10, process: "chrome.exe");
        DayLedger.Add(totals, working: false, seconds: 4, process: "chrome.exe");
        Assert.Equal(50, totals.ActiveSeconds);
        Assert.Equal(9, totals.IdleSeconds);
        Assert.Equal(10, totals.Programs["chrome.exe"]);
        var next = DayLedger.EnsureToday(totals, today.AddDays(1), out closed);
        Assert.Equal(50, closed!.ActiveSeconds);
        Assert.Equal(0, next.ActiveSeconds);
        Assert.Equal("2026-10-21", next.Date);
    }

    [Fact]
    public void SamplesOnOneDateBecomeActiveProgramTime()
    {
        var date = new DateOnly(2026, 10, 20);
        var start = new DateTime(2026, 10, 20, 4, 0, 0, DateTimeKind.Utc);
        var samples = new List<ActivitySample>
        {
            new() { Utc = start, IdleSeconds = 0, Process = "chrome.exe", Title = "Inbox" },
            new() { Utc = start.AddSeconds(20), IdleSeconds = 40, Process = "chrome.exe", Title = "Inbox" },
            new() { Utc = start.AddSeconds(30), IdleSeconds = 50, Process = "chrome.exe", Title = "Inbox" }
        };
        var totals = DayReport.FromSamples(date, samples, alarmAfterSeconds: 30);
        Assert.Equal(20, totals.ActiveSeconds);
        Assert.Equal(10, totals.IdleSeconds);
        Assert.Contains("Active 20 s", DayReport.Describe(date, totals, samples));
        Assert.Contains("Inbox", DayReport.Describe(date, totals, samples));
    }

    [Fact]
    public void DaysListSkipsDatesWithNoConnection()
    {
        var connected = PakistanClock.ConnectedDays(
            new[] { "2026-10-20.json", "notes.txt" },
            new[] { new DateOnly(2026, 10, 18) });
        Assert.Equal(new[] { new DateOnly(2026, 10, 20), new DateOnly(2026, 10, 18) }, connected);
    }

    [Fact]
    public void UntickedDriveStaysHiddenAndATickedDriveOpens()
    {
        var hidden = FolderAccess.HiddenDriveMask(new[] { "Desktop", "Documents" }, new[] { 'C', 'D' });
        Assert.Equal((1 << 2) | (1 << 3), hidden);
        var opened = FolderAccess.HiddenDriveMask(new[] { "Desktop", "C:", @"D:\Projects" }, new[] { 'C', 'D' });
        Assert.Equal(0, opened);
        var view = FolderAccess.ExplorerViewMask(hidden, profileFoldersAllowed: true);
        Assert.Equal(0, view & (1 << 2));
        Assert.NotEqual(0, view & (1 << 3));
        Assert.True(FolderAccess.AllowsProfileFolder(new[] { "Documents" }));
    }
}
