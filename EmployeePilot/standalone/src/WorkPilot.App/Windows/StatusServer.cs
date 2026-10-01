using System.Net;
using System.Text;
using System.Text.Json;
using WorkPilot.Core;

namespace WorkPilot.Windows;

public static class StatusServer
{
    public static void Start()
    {
        var thread = new Thread(Listen)
        {
            IsBackground = true,
            Name = "WorkPilot watch"
        };
        thread.Start();
    }

    private static void Listen()
    {
        try
        {
            var listener = new HttpListener();
            listener.Prefixes.Add($"http://+:{PilotPaths.WatchPort}/");
            listener.Start();
            while (true)
            {
                var context = listener.GetContext();
                var path = context.Request.Url?.AbsolutePath ?? "/";
                var body = path.Equals("/status", StringComparison.OrdinalIgnoreCase)
                    ? JsonSerializer.Serialize(LiveBoard.ReadLocal(), PilotConfigStore.Json)
                    : Page();
                var bytes = Encoding.UTF8.GetBytes(body);
                context.Response.ContentType = path.Equals("/status", StringComparison.OrdinalIgnoreCase)
                    ? "application/json"
                    : "text/html; charset=utf-8";
                context.Response.ContentLength64 = bytes.Length;
                context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                context.Response.Close();
            }
        }
        catch (Exception ex)
        {
            try
            {
                Directory.CreateDirectory(PilotPaths.Logs);
                File.AppendAllText(Path.Combine(PilotPaths.Logs, "tracker.log"), $"{DateTime.UtcNow:o}  Watch page did not start. {ex.Message}{Environment.NewLine}");
            }
            catch
            {
                // The employee window still shows the lights.
            }
        }
    }

    private static string Page() => """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Employee activity</title>
<style>
body { font-family: Segoe UI, sans-serif; margin: 2rem; }
.row { display: flex; gap: 1rem; }
button { font-size: 1.4rem; min-width: 12rem; min-height: 4.5rem; border: 0; border-radius: 8px; }
#detail { margin-top: 1.2rem; font-size: 1.05rem; }
</style>
</head>
<body>
<p>Click this page once so this computer can play the alarm.</p>
<div class="row">
<button id="green" type="button">Working</button>
<button id="red" type="button">Not working</button>
</div>
<p id="detail">Waiting for the employee.</p>
<script>
let audio;
document.body.addEventListener("click", () => { audio = audio || new AudioContext(); }, { once: true });
function beep() {
  if (!audio) return;
  const tone = audio.createOscillator();
  const gain = audio.createGain();
  tone.frequency.value = 880;
  tone.connect(gain);
  gain.connect(audio.destination);
  tone.start();
  setTimeout(() => tone.stop(), 280);
}
async function tick() {
  try {
    const status = await fetch("/status").then(response => response.json());
    const fresh = status.sessionOpen && (Date.now() - Date.parse(status.updatedUtc)) < 15000;
    const working = fresh && status.working;
    document.getElementById("green").style.background = working ? "#148F3E" : "#D9D9D9";
    document.getElementById("green").style.color = working ? "#fff" : "#666";
    document.getElementById("red").style.background = fresh && !status.working ? "#C62828" : "#D9D9D9";
    document.getElementById("red").style.color = fresh && !status.working ? "#fff" : "#666";
    document.getElementById("detail").textContent = fresh
      ? status.program + "  ·  idle " + status.idleSeconds + "s  ·  clicks " + status.clickCount
      : "No employee is signed in.";
    if (fresh && !status.working) beep();
  } catch (error) {
    document.getElementById("detail").textContent = "Cannot reach the work computer.";
  }
}
setInterval(tick, 1200);
tick();
</script>
</body>
</html>
""";
}
