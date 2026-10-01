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
}
