using System.Diagnostics;

namespace WorkPilot.Windows;

internal static class WindowsCommand
{
    public static string SystemTool(string name) => Path.Combine(Environment.SystemDirectory, name);

    public static (int Code, string Output) Run(string file, params string[] args) => Run(file, 60000, args);

    public static (int Code, string Output) Run(string file, int timeoutMs, params string[] args)
    {
        var start = new ProcessStartInfo(file)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true
        };
        foreach (var arg in args)
        {
            start.ArgumentList.Add(arg);
        }
        using var process = Process.Start(start) ?? throw new InvalidOperationException($"Could not start {file}.");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        // Windows tools such as net.exe wait forever when input is left open.
        process.StandardInput.Close();
        if (!process.WaitForExit(timeoutMs))
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch
            {
                // The step already failed. Report that instead of the kill error.
            }
            throw new InvalidOperationException($"{Path.GetFileName(file)} did not finish within {timeoutMs / 1000} seconds.");
        }
        var output = (stdout.Result + stderr.Result).Trim();
        return (process.ExitCode, output);
    }
}
