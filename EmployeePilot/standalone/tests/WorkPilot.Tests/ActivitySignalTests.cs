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
}
