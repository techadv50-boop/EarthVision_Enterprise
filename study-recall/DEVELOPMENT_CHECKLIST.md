# Development checklist

## Phase 1 — Foundation

- [x] Tauri 2 shell with React, TypeScript, and Tailwind
- [x] Navigation for study, oral test, written test, progress, revision, and settings
- [x] SQLite open, foreign keys, WAL, and versioned schema migration
- [x] Light and dark theme

## Phase 2 — Study material

- [x] Student profiles
- [x] Create, rename, reorder, archive, soft-delete, restore, and purge classes, books, chapters, and topics
- [x] Move a topic to another chapter
- [x] Topic search and counts for notes and tests
- [x] Topic editor with reference text, language direction, and concept items
- [x] Draft autosave
- [x] Persistence covered by engine tests

## Phase 3 — Voice

- [x] Microphone capture, pause, resume, stop, and elapsed time
- [x] Local whisper.cpp transcription command
- [x] Explicit unavailable-model message and typed fallback
- [x] English and Urdu language passed to the model, with English-only models refused for Urdu
- [x] Transcript editing and segment combining
- [x] Audio discarded after transcription unless the student opts in

## Phase 4 — Oral recall

- [x] Class, book, and chapter selection
- [x] Random shuffle without repeats
- [x] Spoken or typed answers
- [x] Skip recorded as skipped
- [x] Concept rubric stored by criterion, with approximate or review labeling
- [x] Session summary and reference-beside-answer review

## Phase 5 — Written examination

- [x] Multi-chapter selection
- [x] Question generation only from saved notes
- [x] 30/40/30 paper and smaller feasible papers, with rounding disclosed
- [x] Snapshot stored before the exam starts
- [x] One question at a time, configurable limits, automatic advance
- [x] Draft saved when time expires
- [x] Monotonic timer plus documented recovery after the app closes

## Phase 6 — Results and progress

- [x] Objective and descriptive marking
- [x] Result screen with section scores and per-question reasons
- [x] Print and HTML export for PDF
- [x] Progress by class, subject, chapter, and topic
- [x] Revision categories and a weak-topic oral test
- [x] History kept as separate exam and oral rows

## Phase 7 — Release

- [x] SQLite backup, restore, JSON export, and JSON import
- [x] Integrity check and backup log
- [x] Engine flow tests and frontend unit tests
- [x] NSIS installer configuration and Windows build workflow
- [x] User guide, installation notes, AI limits, and developer notes

## Not bundled in the repository

- [ ] Whisper.cpp binary and GGML model. The student selects these locally. The app explains when they are missing.
- [ ] llama.cpp binary and GGUF model. Descriptive grading uses the labeled rubric until they are selected.
- [ ] A built `.exe` in git. The Windows workflow builds it. This environment can compile the app, but it cannot produce the NSIS installer.
