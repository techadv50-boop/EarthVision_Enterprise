namespace WorkPilot.Core;

public sealed class TimerControl
{
    public bool Running { get; private set; } = true;
    public bool StoppedByCeo { get; private set; }
    public bool ReportDue { get; private set; }
    public bool BeginSession { get; private set; }
    public string Note { get; private set; } = "";

    public void Tick(bool sessionConnected, string? command)
    {
        ReportDue = false;
        BeginSession = false;
        if (string.Equals(command, "reset", StringComparison.Ordinal) || string.Equals(command, "clear", StringComparison.Ordinal))
        {
            Running = true;
            StoppedByCeo = false;
            ReportDue = true;
            BeginSession = true;
            Note = string.Equals(command, "clear", StringComparison.Ordinal) ? "Records cleared." : "";
            return;
        }
        if (string.Equals(command, "stop", StringComparison.Ordinal))
        {
            if (Running)
            {
                Running = false;
                StoppedByCeo = true;
                ReportDue = true;
                Note = "Stopped. The report is saved.";
            }
            return;
        }
        if (!sessionConnected && Running)
        {
            Running = false;
            StoppedByCeo = false;
            ReportDue = true;
            Note = "Employee disconnected. The report is saved.";
            return;
        }
        if (sessionConnected && !Running && !StoppedByCeo)
        {
            Running = true;
            BeginSession = true;
            Note = "";
        }
    }
}

public static class TimerCommand
{
    public static string Format(string action, DateTime issuedUtc) =>
        action + "|" + issuedUtc.ToUniversalTime().ToString("o");

    public static bool TryParse(string? text, out string action, out DateTime issuedUtc)
    {
        action = "";
        issuedUtc = default;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }
        var parts = text.Trim().Split('|');
        if (parts.Length != 2)
        {
            return false;
        }
        if (parts[0] is not ("stop" or "reset" or "clear"))
        {
            return false;
        }
        if (!DateTime.TryParse(parts[1], null, System.Globalization.DateTimeStyles.RoundtripKind, out issuedUtc))
        {
            return false;
        }
        action = parts[0];
        return true;
    }
}
