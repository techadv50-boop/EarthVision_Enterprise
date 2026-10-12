# Installation

Study Recall is a desktop application for Windows 10 and Windows 11. It does not need an account, and it does not send notes, recordings, or answers to a server.

## Install on Windows

1. Download `Study Recall_1.0.0_x64-setup.exe` from the Windows installer workflow artifact, or build it with the commands below.
2. Run the installer. It installs for the current Windows user.
3. Open Study Recall from the Start menu.
4. In Settings, create a student profile. That profile is stored in a local SQLite file.

The first launch creates the database under the per-user application data folder. The exact path is shown in Settings and Backup.

## Build the installer

The installer is an NSIS package produced by Tauri on Windows:

```powershell
cd study-recall
npm ci
npm test
cargo test -p study-core
npx tauri build
```

The setup program is written to `study-recall/src-tauri/target/release/bundle/nsis/`.

Rust 1.90 and Node.js 22 are required. WebView2 is included with Windows 11 and with current Windows 10 updates.

GitHub Actions workflow `.github/workflows/windows-installer.yml` runs the same build on `windows-latest` and uploads the installer.

## Linux and macOS

The application logic and the desktop window also build where Tauri supports the platform. The Windows NSIS installer is the release package for this project. On Linux, install the WebKitGTK 4.1 development packages before `cargo build`.

## Updates

An update does not delete the SQLite database. Schema changes are applied by numbered migrations inside the database. Export a JSON copy or a SQLite backup from Settings before upgrading if you want a separate copy.

## Offline speech and grading models

Speech recognition and model-based grading are optional. The application works with typed answers when those programs are not installed. To enable them, install the tools locally and select the files in Settings:

- whisper.cpp `whisper-cli` (or the equivalent CLI that accepts `-m`, `-f`, `-otxt`, and `-l`)
- a Whisper GGML model, preferably multilingual `ggml-small.bin` or larger
- llama.cpp `llama-cli` and a local GGUF model, if you want model-assisted descriptive grading

Do not select an English-only Whisper model for Urdu. The application refuses that combination and explains why.

## Hardware

Typed study, oral scoring with the built-in rubric, and written exams do not need a GPU.

Local transcription and llama.cpp grading are much heavier:

- 8 GB of memory is a practical minimum for a small Whisper model plus the desktop app.
- A small multilingual Whisper model can use several gigabytes while it runs and may take longer than the recording.
- llama.cpp grading needs additional memory for the chosen GGUF model. A 7-billion-parameter model typically wants 8 GB or more of free memory and is still an estimate, not a teacher’s mark.
- A GPU is optional. CPU inference is slower but keeps the work on the computer.

Recordings are deleted after transcription unless Settings has “Keep recordings” turned on.
