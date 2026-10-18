# Installation

Study Recall is a desktop application for Windows 10 and Windows 11. It does not need an account, and it does not send notes, recordings, or answers to a server.

## Install on Windows

1. Download `Study Recall_1.1.0_x64-setup.exe` from the Windows installer workflow artifact, or build it with the commands below.
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

The setup program is written to `study-recall/target/release/bundle/nsis/`.

The Windows build also downloads whisper.cpp and the multilingual `ggml-small.bin` model and places them inside the installer. After installation, Record voice and Transcribe voice use those files. No separate speech download is required. Reading a prompt aloud uses the speaking voice already included with Windows.

Rust 1.90 and Node.js 22 are required. WebView2 is included with Windows 11 and with current Windows 10 updates.

GitHub Actions workflow `.github/workflows/windows-installer.yml` runs the same build on `windows-latest` and uploads the installer.

## Linux and macOS

The application logic and the desktop window also build where Tauri supports the platform. The Windows NSIS installer is the release package for this project. On Linux, install the WebKitGTK 4.1 development packages before `cargo build`.

## Updates

An update does not delete the SQLite database. Schema changes are applied by numbered migrations inside the database. Export a JSON copy or a SQLite backup from Settings before upgrading if you want a separate copy.

## Offline speech and grading models

Speech recognition is included in the Windows installer. Record voice and Transcribe voice use the whisper.cpp program and the multilingual `ggml-small.bin` model that the installer places on the computer. Listening to a prompt or a note uses the speaking voice that is already part of Windows. No extra download is required after installation.

Typing and pasting still work if the microphone is unavailable. If Windows has no Urdu speaking voice, Listen says so and leaves the text on screen.

llama.cpp grading is still optional. Descriptive scores use the labeled approximate rubric until a local llama.cpp program and model are selected in Settings. Replace the included speech files from Settings only if you want a different local model.

Do not select an English-only Whisper model for Urdu. The application refuses that combination and explains why.

## Hardware

Typed study, oral scoring with the built-in rubric, and written exams do not need a GPU.

Local transcription and llama.cpp grading are much heavier:

- 8 GB of memory is a practical minimum for a small Whisper model plus the desktop app.
- A small multilingual Whisper model can use several gigabytes while it runs and may take longer than the recording.
- llama.cpp grading needs additional memory for the chosen GGUF model. A 7-billion-parameter model typically wants 8 GB or more of free memory and is still an estimate, not a teacher’s mark.
- A GPU is optional. CPU inference is slower but keeps the work on the computer.

Recordings are deleted after transcription unless Settings has “Keep recordings” turned on.
