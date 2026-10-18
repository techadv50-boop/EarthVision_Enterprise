# Study Recall

Study Recall is an offline desktop application for organizing study notes, practicing oral recall, and sitting written exams generated only from those notes.

The interface is Tauri 2, React, and TypeScript. The study rules, SQLite database, grading, and exam timer live in the `study-core` Rust crate. The Windows installer includes whisper.cpp and a multilingual speech model, so recording notes and transcribing them works after installation. Listening uses the speaking voice included with Windows. A Word file that is already arranged chapter by chapter can be placed onto the open book’s chapter and topic shelves. Descriptive grading can use a local llama.cpp program when one is selected. None of these are replaced with a cloud service when a local program is missing.

## Use it

- [Installation](docs/INSTALLATION.md)
- [User guide](docs/USER_GUIDE.md)
- [Speech and grading limits](docs/AI_LIMITATIONS.md)
- [Developer notes](docs/DEVELOPER.md)
- [Checklist](DEVELOPMENT_CHECKLIST.md)

## Tests

```bash
cargo test -p study-core
npm test
npm run typecheck
```

The engine flow test creates a class, book, chapter, and topics, runs an oral test, generates a written paper, advances a timed exam, marks it, and checks backup and restore.
