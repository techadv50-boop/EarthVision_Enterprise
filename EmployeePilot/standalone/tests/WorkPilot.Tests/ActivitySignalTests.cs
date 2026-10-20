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
}
