use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use wait_timeout::ChildExt;

use crate::grading::{parse_model_grade, ConceptGrade};
use crate::textutil::combine_transcripts;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SpeechOutcome {
    pub ok: bool,
    pub text: String,
    pub method: String,
    pub language: String,
    pub warning: String,
    pub error_code: String,
    pub error_message: String,
    pub retained_path: String,
}

#[derive(Debug, Clone)]
pub struct SpeechConfig {
    pub binary_path: String,
    pub model_path: String,
}

#[derive(Debug, Clone)]
pub struct ProcessOutput {
    pub status: i32,
    pub stdout: String,
    pub stderr: String,
}

pub trait ProcessRunner {
    fn run(
        &self,
        program: &Path,
        args: &[String],
        work_dir: &Path,
    ) -> Result<ProcessOutput, String>;
}

/// Runs a local binary and stops it if it exceeds the time limit.
pub struct BlockingRunner;

impl ProcessRunner for BlockingRunner {
    fn run(
        &self,
        program: &Path,
        args: &[String],
        work_dir: &Path,
    ) -> Result<ProcessOutput, String> {
        let child = Command::new(program)
            .args(args)
            .current_dir(work_dir)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|err| format!("The speech program could not be started: {err}"))?;
        finish_child(child, Duration::from_secs(15 * 60))
    }
}

fn finish_child(mut child: std::process::Child, timeout: Duration) -> Result<ProcessOutput, String> {
    use std::io::Read;
    let status = child.wait_timeout(timeout).map_err(|err| err.to_string())?;
    let status = match status {
        Some(status) => status,
        None => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(
                "The local model took too long and was stopped. You can type the text instead."
                    .into(),
            );
        }
    };
    let mut stdout = String::new();
    let mut stderr = String::new();
    if let Some(mut pipe) = child.stdout.take() {
        pipe.read_to_string(&mut stdout).map_err(|err| err.to_string())?;
    }
    if let Some(mut pipe) = child.stderr.take() {
        pipe.read_to_string(&mut stderr).map_err(|err| err.to_string())?;
    }
    Ok(ProcessOutput {
        status: status.code().unwrap_or(1),
        stdout,
        stderr,
    })
}

pub fn unavailable(message: impl Into<String>) -> SpeechOutcome {
    SpeechOutcome {
        ok: false,
        text: String::new(),
        method: String::new(),
        language: String::new(),
        warning: String::new(),
        error_code: "model_unavailable".into(),
        error_message: message.into(),
        retained_path: String::new(),
    }
}

pub fn assess_whisper(binary: &str, model: &str) -> (bool, String) {
    if binary.trim().is_empty() || !Path::new(binary).is_file() {
        return (
            false,
            "The speech program included with Study Recall was not found. You can type or paste text. Whisper stays on this computer and is not replaced by an online service.".into(),
        );
    }
    if model.trim().is_empty() || !Path::new(model).is_file() {
        return (
            false,
            "The multilingual speech model included with Study Recall was not found. You can type or paste text until the installation is repaired.".into(),
        );
    }
    (
        true,
        "Speech recognition is ready on this computer. Record voice, then choose Transcribe voice. Nothing is sent to a server.".into(),
    )
}

pub fn assess_llama(binary: &str, model: &str) -> (bool, String) {
    if binary.trim().is_empty() || !Path::new(binary).is_file() {
        return (
            false,
            "A local language model is not configured. Descriptive scores use the approximate concept rubric, which is labeled in every result.".into(),
        );
    }
    if model.trim().is_empty() || !Path::new(model).is_file() {
        return (
            false,
            "The llama.cpp program was found, but its model file is missing. Descriptive scores use the approximate concept rubric until a model is selected.".into(),
        );
    }
    (
        true,
        "A local llama.cpp model is configured. Descriptive scores are estimates from that model.".into(),
    )
}

pub fn english_only_model(model_path: &str) -> bool {
    let name = Path::new(model_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    name.contains(".en.") || name.ends_with(".en.bin") || name.ends_with(".en.gguf")
}

pub fn whisper_args(model: &Path, wav: &Path, language: &str) -> Vec<String> {
    let mut args = vec![
        "-m".into(),
        model.display().to_string(),
        "-f".into(),
        wav.display().to_string(),
        "-otxt".into(),
    ];
    if language != "auto" && !language.is_empty() {
        args.push("-l".into());
        args.push(language.into());
    }
    args
}

pub fn transcribe_wav<R: ProcessRunner>(
    runner: &R,
    config: &SpeechConfig,
    wav_bytes: &[u8],
    language: &str,
    work_dir: &Path,
    retain: bool,
) -> SpeechOutcome {
    let (ready, message) = assess_whisper(&config.binary_path, &config.model_path);
    if !ready {
        return unavailable(message);
    }
    if language == "ur" && english_only_model(&config.model_path) {
        return unavailable(
            "The selected Whisper model is English-only. Choose a multilingual model such as ggml-small.bin before transcribing Urdu.",
        );
    }
    if let Err(err) = validate_wav(wav_bytes) {
        return SpeechOutcome {
            ok: false,
            text: String::new(),
            method: String::new(),
            language: language.into(),
            warning: String::new(),
            error_code: "invalid_audio".into(),
            error_message: err,
            retained_path: String::new(),
        };
    }
    if let Err(err) = fs::create_dir_all(work_dir) {
        return failed(err.to_string());
    }
    let wav_path = work_dir.join("capture.wav");
    if let Err(err) = fs::write(&wav_path, wav_bytes) {
        return failed(format!("The recording could not be saved for transcription: {err}"));
    }
    let args = whisper_args(Path::new(&config.model_path), &wav_path, language);
    let result = runner.run(Path::new(&config.binary_path), &args, work_dir);
    let transcript = match result {
        Ok(output) => {
            if output.status != 0 && output.stdout.trim().is_empty() {
                let stderr = output.stderr.chars().take(400).collect::<String>();
                cleanup(&wav_path, work_dir, false);
                return failed(format!("Whisper.cpp did not transcribe the recording. {stderr}"));
            }
            let file_text = fs::read_to_string(work_dir.join("capture.wav.txt")).unwrap_or_default();
            let text = if file_text.trim().is_empty() {
                clean_whisper_output(&output.stdout)
            } else {
                clean_whisper_output(&file_text)
            };
            text
        }
        Err(err) => {
            cleanup(&wav_path, work_dir, false);
            return failed(err);
        }
    };
    if transcript.trim().is_empty() {
        cleanup(&wav_path, work_dir, false);
        return failed(
            "Whisper.cpp finished without producing text. You can type the transcript, or try a larger multilingual model.".into(),
        );
    }
    let retained_path = if retain {
        let kept = work_dir.join("retained-capture.wav");
        let _ = fs::rename(&wav_path, &kept);
        kept.display().to_string()
    } else {
        cleanup(&wav_path, work_dir, false);
        String::new()
    };
    if !retain {
        let _ = fs::remove_file(work_dir.join("capture.wav.txt"));
    }
    let mut warning = String::new();
    let model_name = Path::new(&config.model_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("");
    if language == "ur" && (model_name.contains("tiny") || model_name.contains("base")) {
        warning = "Urdu transcription with a tiny or base Whisper model is often unreliable. Read the transcript and correct it before saving.".into();
    }
    SpeechOutcome {
        ok: true,
        text: transcript.trim().to_string(),
        method: "whisper.cpp".into(),
        language: language.into(),
        warning,
        error_code: String::new(),
        error_message: String::new(),
        retained_path,
    }
}

fn cleanup(wav_path: &Path, work_dir: &Path, _retain: bool) {
    let _ = fs::remove_file(wav_path);
    let _ = fs::remove_file(work_dir.join("capture.wav.txt"));
}

fn failed(message: String) -> SpeechOutcome {
    SpeechOutcome {
        ok: false,
        text: String::new(),
        method: String::new(),
        language: String::new(),
        warning: String::new(),
        error_code: "transcription_failed".into(),
        error_message: message,
        retained_path: String::new(),
    }
}

pub fn validate_wav(bytes: &[u8]) -> Result<(), String> {
    if bytes.len() < 44 {
        return Err("The recording was empty. Record again or type the text.".into());
    }
    if &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return Err(
            "The recording was not a WAV file. Record again from the microphone button or type the text."
                .into(),
        );
    }
    Ok(())
}

pub fn synthesize_test_wav(samples: &[i16], sample_rate: u32) -> Vec<u8> {
    let data_len = (samples.len() * 2) as u32;
    let mut bytes = Vec::with_capacity(44 + data_len as usize);
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&(36 + data_len).to_le_bytes());
    bytes.extend_from_slice(b"WAVE");
    bytes.extend_from_slice(b"fmt ");
    bytes.extend_from_slice(&16u32.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&sample_rate.to_le_bytes());
    bytes.extend_from_slice(&(sample_rate * 2).to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&16u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        bytes.extend_from_slice(&sample.to_le_bytes());
    }
    bytes
}

pub fn clean_whisper_output(raw: &str) -> String {
    let mut lines = Vec::new();
    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.starts_with('[') {
            if let Some(idx) = trimmed.find(']') {
                let rest = trimmed[idx + 1..].trim();
                if !rest.is_empty() {
                    lines.push(rest.to_string());
                }
                continue;
            }
        }
        lines.push(trimmed.to_string());
    }
    lines.join(" ")
}

pub fn merge_segments(parts: &[impl AsRef<str>]) -> String {
    combine_transcripts(parts)
}

pub fn try_llama_grade(
    binary: &str,
    model: &str,
    reference: &str,
    answer: &str,
    points: &[String],
) -> Option<ConceptGrade> {
    let (ready, _) = assess_llama(binary, model);
    if !ready {
        return None;
    }
    let reference = truncate(reference, 4000);
    let answer = truncate(answer, 4000);
    let points = points.join("\n");
    let prompt = format!(
        "Grade the student answer against the reference. Reply with JSON only, no markdown. Fields essential, factual, supporting are numbers from 0 to 1. Fields covered, missing, incorrect are arrays of short strings.\nReference:\n{reference}\nExpected points:\n{points}\nStudent:\n{answer}\nJSON:"
    );
    let child = Command::new(binary)
        .arg("-m")
        .arg(model)
        .arg("-p")
        .arg(prompt)
        .arg("-n")
        .arg("400")
        .arg("--temp")
        .arg("0.1")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .ok()?;
    let output = finish_child(child, Duration::from_secs(90)).ok()?;
    if output.status != 0 {
        return None;
    }
    parse_model_grade(&output.stdout)
}

fn truncate(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        text.to_string()
    } else {
        text.chars().take(max_chars).collect::<String>()
    }
}

/// Decode a data URL or plain base64 payload into bytes.
pub fn decode_audio_payload(payload: &str) -> Result<Vec<u8>, String> {
    let data = payload
        .split_once("base64,")
        .map(|(_, rest)| rest)
        .unwrap_or(payload)
        .trim();
    base64::Engine::decode(&base64::engine::general_purpose::STANDARD, data)
        .map_err(|_| "The recording could not be read. Record again or type the text.".into())
}

pub fn decode_audio_allowing_whitespace(payload: &str) -> Result<Vec<u8>, String> {
    let data = payload
        .split_once("base64,")
        .map(|(_, rest)| rest)
        .unwrap_or(payload);
    let compact: String = data.chars().filter(|c| !c.is_whitespace()).collect();
    base64::Engine::decode(&base64::engine::general_purpose::STANDARD, compact)
        .map_err(|_| "The recording could not be read. Record again or type the text.".into())
}

pub struct ScriptedRunner {
    pub stdout: String,
    pub status: i32,
    pub calls: std::sync::Mutex<Vec<Vec<String>>>,
}

impl ProcessRunner for ScriptedRunner {
    fn run(
        &self,
        _program: &Path,
        args: &[String],
        work_dir: &Path,
    ) -> Result<ProcessOutput, String> {
        if let Ok(mut calls) = self.calls.lock() {
            calls.push(args.to_vec());
        }
        let mut file = fs::File::create(work_dir.join("capture.wav.txt"))
            .map_err(|err| err.to_string())?;
        file.write_all(self.stdout.as_bytes())
            .map_err(|err| err.to_string())?;
        Ok(ProcessOutput {
            status: self.status,
            stdout: self.stdout.clone(),
            stderr: String::new(),
        })
    }
}

/// Locates the speech program and multilingual model shipped inside the installation.
pub fn bundled_speech_paths(root: &Path) -> Option<(PathBuf, PathBuf)> {
    let binary = find_named(root, &["whisper-cli.exe", "whisper-cli"], 0)?;
    let model = find_matching(root, 0, |name| {
        let lower = name.to_ascii_lowercase();
        lower.starts_with("ggml") && lower.ends_with(".bin") && !lower.contains(".en.")
    })?;
    Some((binary, model))
}

/// Points speech recognition at the installed program when the saved paths are missing.
pub fn apply_bundled_whisper(db: &mut crate::Database, root: &Path) -> crate::error::AppResult<bool> {
    let Some((binary, model)) = bundled_speech_paths(root) else {
        return Ok(false);
    };
    let models = db.get_models()?;
    let Some(whisper) = models.iter().find(|item| item.kind == "whisper") else {
        return Ok(false);
    };
    let ready = Path::new(&whisper.binary_path).is_file() && Path::new(&whisper.model_path).is_file();
    if ready {
        return Ok(false);
    }
    db.update_model(
        "whisper",
        &binary.display().to_string(),
        &model.display().to_string(),
    )?;
    Ok(true)
}

fn find_named(root: &Path, names: &[&str], depth: usize) -> Option<PathBuf> {
    find_matching(root, depth, |name| names.iter().any(|wanted| name.eq_ignore_ascii_case(wanted)))
}

fn find_matching(root: &Path, depth: usize, pred: impl Fn(&str) -> bool + Copy) -> Option<PathBuf> {
    if depth > 5 || !root.is_dir() {
        return None;
    }
    let entries = fs::read_dir(root).ok()?;
    let mut dirs = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file() {
            if let Some(name) = path.file_name().and_then(|item| item.to_str()) {
                if pred(name) {
                    return Some(path);
                }
            }
        } else if path.is_dir() {
            dirs.push(path);
        }
    }
    for dir in dirs {
        if let Some(found) = find_matching(&dir, depth + 1, pred) {
            return Some(found);
        }
    }
    None
}

pub fn work_dir_for(parent: &Path) -> PathBuf {
    parent.join(format!("speech-{}", uuid::Uuid::new_v4()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[test]
    fn missing_model_does_not_pretend_to_transcribe() {
        let runner = ScriptedRunner {
            stdout: "should not be used".into(),
            status: 0,
            calls: Mutex::new(vec![]),
        };
        let wav = synthesize_test_wav(&[0, 100, -100, 0], 16_000);
        let dir = std::env::temp_dir().join(format!("study-recall-missing-{}", uuid::Uuid::new_v4()));
        let outcome = transcribe_wav(
            &runner,
            &SpeechConfig { binary_path: String::new(), model_path: String::new() },
            &wav,
            "en",
            &dir,
            false,
        );
        assert!(!outcome.ok);
        assert_eq!(outcome.error_code, "model_unavailable");
        assert!(outcome.error_message.contains("Whisper"));
        assert!(runner.calls.lock().unwrap().is_empty());
        assert!(outcome.text.is_empty());
    }

    #[test]
    fn bundled_multilingual_model_is_used_when_saved_paths_are_missing() {
        let dir = std::env::temp_dir().join(format!("study-recall-bundle-{}", uuid::Uuid::new_v4()));
        let speech = dir.join("nested").join("speech");
        fs::create_dir_all(&speech).unwrap();
        let binary = speech.join("whisper-cli.exe");
        let model = speech.join("ggml-small.bin");
        fs::write(&binary, b"cli").unwrap();
        fs::write(&model, b"model").unwrap();
        fs::write(speech.join("ggml-small.en.bin"), b"english-only").unwrap();
        let mut db = crate::Database::open(dir.join("study.sqlite")).unwrap();
        assert!(apply_bundled_whisper(&mut db, &dir).unwrap());
        let models = db.get_models().unwrap();
        let whisper = models.iter().find(|item| item.kind == "whisper").unwrap();
        assert_eq!(whisper.binary_path, binary.display().to_string());
        assert!(whisper.model_path.ends_with("ggml-small.bin"));
        assert!(!whisper.model_path.contains(".en."));
        assert!(!apply_bundled_whisper(&mut db, &dir).unwrap());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn scripted_runner_transcribes_test_audio_and_discards_it() {
        let dir = std::env::temp_dir().join(format!("study-recall-speech-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        let binary = dir.join("whisper-cli");
        let model = dir.join("ggml-small.bin");
        fs::write(&binary, b"bin").unwrap();
        fs::write(&model, b"model").unwrap();
        let runner = ScriptedRunner {
            stdout: "[00:00:00.000 --> 00:00:01.000]  resting potential".into(),
            status: 0,
            calls: Mutex::new(vec![]),
        };
        let wav = synthesize_test_wav(&[0, 1000, -1000, 50], 16_000);
        let work = dir.join("work");
        let outcome = transcribe_wav(
            &runner,
            &SpeechConfig {
                binary_path: binary.display().to_string(),
                model_path: model.display().to_string(),
            },
            &wav,
            "en",
            &work,
            false,
        );
        assert!(outcome.ok, "{:?}", outcome.error_message);
        assert_eq!(outcome.text, "resting potential");
        assert_eq!(outcome.method, "whisper.cpp");
        assert!(!work.join("capture.wav").exists());
        let args = runner.calls.lock().unwrap();
        assert_eq!(args.len(), 1);
        assert!(args[0].contains(&"-m".to_string()));
        assert!(args[0].contains(&"en".to_string()));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn english_only_model_refuses_urdu() {
        let dir = std::env::temp_dir().join(format!("study-recall-en-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        let binary = dir.join("whisper-cli");
        let model = dir.join("ggml-tiny.en.bin");
        fs::write(&binary, b"bin").unwrap();
        fs::write(&model, b"model").unwrap();
        let runner = ScriptedRunner {
            stdout: "no".into(),
            status: 0,
            calls: Mutex::new(vec![]),
        };
        let wav = synthesize_test_wav(&[1, 2, 3, 4], 16_000);
        let outcome = transcribe_wav(
            &runner,
            &SpeechConfig {
                binary_path: binary.display().to_string(),
                model_path: model.display().to_string(),
            },
            &wav,
            "ur",
            &dir.join("work"),
            false,
        );
        assert_eq!(outcome.error_code, "model_unavailable");
        assert!(outcome.error_message.contains("multilingual"));
        assert!(runner.calls.lock().unwrap().is_empty());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn segments_combine_and_whisper_timestamps_are_stripped() {
        assert_eq!(
            merge_segments(&["  first sentence. ", "", "دوسرا جملہ"]),
            "first sentence.\nدوسرا جملہ"
        );
        assert_eq!(
            clean_whisper_output("[00:00:00.000 --> 00:00:01.000]  hello\n\nworld"),
            "hello world"
        );
    }

    #[test]
    fn invalid_audio_is_rejected() {
        let runner = ScriptedRunner {
            stdout: String::new(),
            status: 0,
            calls: Mutex::new(vec![]),
        };
        let dir = std::env::temp_dir();
        let outcome = transcribe_wav(
            &runner,
            &SpeechConfig { binary_path: "x".into(), model_path: "y".into() },
            b"not-a-wav",
            "en",
            &dir,
            false,
        );
        assert_eq!(outcome.error_code, "model_unavailable");
    }
}
