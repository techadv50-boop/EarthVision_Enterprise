# Developer notes

## Layout

- `crates/study-core` holds SQLite, the study hierarchy, Word import, speech invocation, oral scoring, exam generation, timing, marking, progress, and backup.
- `src-tauri` is the Tauri 2 shell. Commands are thin wrappers around `study-core`.
- `src` is the React interface.

The desktop window calls Tauri commands. It does not embed a second copy of the grading rules.

## Database

`Database::open` enables foreign keys and WAL mode, then applies `schema_migrations`. Version 1 creates the study, exam, settings, and model tables. Student rows are not seeded. Upgrades must add a new migration version instead of recreating the file.

Important tables include student profiles, classes, books, chapters, topics, topic notes, key concepts, oral sessions and scores, written exams, questions, answers, results, revision status, settings, and model configuration.

Deleting a class, book, chapter, or topic sets `deleted_at`. Restore clears it. Purge requires the confirmation text `DELETE` and removes the row. Archive is separate and hides an item while keeping it available to tests only when the caller asks for archived rows. Tests use rows that are not deleted.

Generated exam questions store the prompt, answer, options, rubric, marks, source topic, and source passage. Later edits to a topic do not rewrite that snapshot.

## Timing policy

The active question stores a wall-clock start, a duration, and a generation number. The window counts down with `performance.now()`. When it sends an expiry, it sends that generation and the monotonic elapsed time, so a changed system clock does not expire or reset the question.

A sync without a generation uses the saved wall start. That is the recovery path after the window is closed: only the active question is settled, and the following question starts with a full duration. Pending transcription does not block the next question. Final marks wait until pending rows are resolved or marked `transcription_failed`.

## Speech

`transcribe_wav` checks the binary and model, rejects an English-only model for Urdu, validates the WAV header, and runs the local process with a timeout. The Tauri command does this off the UI thread. On startup the shell points speech recognition at `whisper-cli` and `ggml-small.bin` when those files are inside the installation and the saved paths are missing. The command returns a `SpeechOutcome` with `ok: false` and a specific message when the model is missing. It does not call a network API.

`import_word_into_book` reads a `.docx` file and places Heading 1 or “Chapter” lines on chapter shelves and Heading 2–4 or “Topic” lines on topic shelves in the open book. Existing notes are not overwritten.

Listen uses the Windows speaking voice through `System.Speech`. It does not download a voice. If that voice is absent, the text stays on screen.

## Tests

From `study-recall`:

```bash
cargo test -p study-core
npm test
npm run typecheck
```

`cargo test -p study-core` includes the end-to-end flow tests:

- hierarchy persistence, Urdu text, and trash restore
- oral shuffle without repeats, and paraphrase scoring
- written exam timing, advancement, marking, snapshot, and backup
- speech transcription of a generated WAV through the test runner
- a wrong objective answer scoring zero

The flow builds Class 10, Biology, a chapter, and topics in a temporary database. It does not use fixed demonstration scores in the interface.

Frontend tests cover WAV encoding and the monotonic exam timer helper.

## Desktop build

```bash
npm install
npm run tauri dev
```

`npm run tauri build` on Windows produces the NSIS installer configured in `src-tauri/tauri.conf.json`.

## Privacy

Commands read and write the local database and local model processes only. There is no login and no telemetry in this project.
