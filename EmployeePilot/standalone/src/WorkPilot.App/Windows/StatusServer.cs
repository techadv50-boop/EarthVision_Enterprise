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
                ThreadPool.QueueUserWorkItem(_ => Serve(context));
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

    private static void Serve(HttpListenerContext context)
    {
        try
        {
            var path = context.Request.Url?.AbsolutePath ?? "/";
            if (path.Equals("/screen.jpg", StringComparison.OrdinalIgnoreCase))
            {
                var jpeg = ScreenGrab.Current();
                if (jpeg is null)
                {
                    context.Response.StatusCode = 503;
                    context.Response.Close();
                    return;
                }
                context.Response.ContentType = "image/jpeg";
                context.Response.Headers["Cache-Control"] = "no-store";
                context.Response.ContentLength64 = jpeg.Length;
                context.Response.OutputStream.Write(jpeg, 0, jpeg.Length);
                context.Response.Close();
                return;
            }
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
        catch
        {
            try
            {
                context.Response.Abort();
            }
            catch
            {
                // The browser will request the next frame.
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
body { font-family: Segoe UI, sans-serif; margin: 1rem; background: #101410; color: #f4f7f5; }
.row { display: flex; gap: 0.6rem; align-items: center; }
button { font-size: 1rem; min-width: 8rem; min-height: 2.4rem; border: 0; border-radius: 8px; }
#detail { margin: 0.6rem 0 0.8rem; font-size: 1rem; white-space: pre-wrap; }
#live { width: 100%; max-height: calc(100vh - 9rem); object-fit: contain; background: #000; border-radius: 8px; display: block; }
</style>
</head>
<body>
<p>Click this page once so this computer can play the alarm.</p>
<div class="row">
<button id="green" type="button">Working</button>
<button id="red" type="button">Not working</button>
</div>
<pre id="detail">Waiting for the employee.</pre>
<img id="live" alt="Live employee screen">
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
    const running = fresh && status.timerRunning !== false;
    const working = running && status.working;
    document.getElementById("green").style.background = working ? "#148F3E" : "#D9D9D9";
    document.getElementById("green").style.color = working ? "#fff" : "#666";
    document.getElementById("red").style.background = running && !status.working ? "#C62828" : "#D9D9D9";
    document.getElementById("red").style.color = running && !status.working ? "#fff" : "#666";
    function duration(seconds) {
      seconds = seconds || 0;
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      const rest = seconds % 60;
      if (hours > 0) return hours + " h " + minutes + " min";
      if (minutes > 0) return minutes + " min " + rest + " s";
      return rest + " s";
    }
    document.getElementById("detail").textContent = fresh
      ? "Active " + duration(status.activeSeconds) + "\nIdle " + duration(status.sessionIdleSeconds) + "\nIdle now " + (status.idleSeconds || 0) + " s" + (status.timerRunning === false ? "\n" + (status.timerNote || "Timer stopped") : "")
      : "No employee is signed in.";
    if (running && !status.working) beep();
  } catch (error) {
    document.getElementById("detail").textContent = "Cannot reach the work computer.";
  }
}
function frame() {
  const live = document.getElementById("live");
  const next = new Image();
  next.onload = () => { live.src = next.src; };
  next.src = "/screen.jpg?t=" + Date.now();
}
setInterval(tick, 1200);
setInterval(frame, 350);
tick();
frame();
</script>
</body>
</html>
""";
}
