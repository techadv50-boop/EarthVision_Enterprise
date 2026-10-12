# Study Recall

Study Recall is an offline desktop application for organizing study notes, practicing oral recall, and sitting written exams generated only from those notes.

The interface is Tauri 2, React, and TypeScript. The study rules, SQLite database, grading, and exam timer live in the `study-core` Rust crate. Speech recognition and descriptive grading can call local whisper.cpp and llama.cpp programs. They are not replaced with a cloud service when those programs are missing.

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
