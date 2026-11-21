use std::process::{Command, Stdio};
use std::time::Duration;

use wait_timeout::ChildExt;

/// Reads text with the speaking voice included on this computer.
pub fn speak_text(text: &str, language: &str) -> Result<String, String> {
    let text = text.trim();
    if text.is_empty() {
        return Err("There is no text to read aloud.".into());
    }
    if text.chars().count() > 4_000 {
        return Err("That passage is too long to read in one step.".into());
    }
    let prefix = if language == "ur" { "ur" } else { "en" };
    #[cfg(windows)]
    {
        speak_windows(text, prefix)
    }
    #[cfg(not(windows))]
    {
        let _ = prefix;
        Err("Reading aloud uses the speaking voice included with Windows.".into())
    }
}

#[cfg(windows)]
fn speak_windows(text: &str, prefix: &str) -> Result<String, String> {
    let dir = std::env::temp_dir().join(format!("study-recall-speak-{}", uuid_stamp()));
    std::fs::create_dir_all(&dir).map_err(|err| err.to_string())?;
    let text_path = dir.join("speech.txt");
    let script_path = dir.join("speak.ps1");
    let mut bytes = vec![0xEF, 0xBB, 0xBF];
    bytes.extend(text.as_bytes());
    std::fs::write(&text_path, bytes).map_err(|err| err.to_string())?;
    std::fs::write(
        &script_path,
        r#"$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$prefix = $env:STUDY_RECALL_LANG
if ([string]::IsNullOrWhiteSpace($prefix)) { $prefix = 'en' }
$match = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name.ToLowerInvariant().StartsWith($prefix.ToLowerInvariant()) })
if ($match.Count -eq 0) { [Console]::Error.WriteLine('NO_VOICE'); exit 2 }
$synth.SelectVoice($match[0].VoiceInfo.Name)
$spoken = Get-Content -Raw -Encoding UTF8 -LiteralPath $env:STUDY_RECALL_FILE
$synth.Speak($spoken)
"#,
    )
    .map_err(|err| err.to_string())?;
    let mut child = Command::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            &script_path.display().to_string(),
        ])
        .env("STUDY_RECALL_LANG", prefix)
        .env("STUDY_RECALL_FILE", text_path.display().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("The Windows speaking voice could not be started: {err}"))?;
    let finished = child
        .wait_timeout(Duration::from_secs(180))
        .map_err(|err| err.to_string())?;
    let status = match finished {
        Some(status) => status,
        None => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = std::fs::remove_dir_all(&dir);
            return Err("Reading aloud took too long and was stopped.".into());
        }
    };
    let mut stderr = String::new();
    if let Some(mut pipe) = child.stderr.take() {
        let _ = std::io::Read::read_to_string(&mut pipe, &mut stderr);
    }
    let _ = std::fs::remove_dir_all(&dir);
    if status.code() == Some(2) || stderr.contains("NO_VOICE") {
        return Err(if prefix == "ur" {
            "This computer has no Urdu speaking voice installed with Windows. The text stays on screen, and you can still record your answer.".into()
        } else {
            "This computer has no English speaking voice installed with Windows. The text stays on screen.".into()
        });
    }
    if !status.success() {
        return Err(format!(
            "The speaking voice could not read that text. {}",
            stderr.chars().take(240).collect::<String>()
        ));
    }
    Ok(if prefix == "ur" {
        "Reading the Urdu text with the Windows voice.".into()
    } else {
        "Reading aloud with the Windows voice included on this computer.".into()
    })
}

#[cfg(windows)]
fn uuid_stamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().to_string())
        .unwrap_or_else(|_| "0".into())
}
