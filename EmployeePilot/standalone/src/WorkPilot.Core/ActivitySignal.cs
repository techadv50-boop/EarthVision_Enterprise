namespace WorkPilot.Core;

public static class ActivitySignal
{
    public static bool IsWorking(int idleSeconds, bool locked, int alarmAfterSeconds) =>
        !locked && idleSeconds < alarmAfterSeconds;
}
