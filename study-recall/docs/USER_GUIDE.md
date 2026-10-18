# Study Recall user guide

Study Recall helps you store what you are studying, say it back from memory, and sit a written paper made only from your own notes.

## Start

1. Open the app.
2. Go to Settings and create a student profile.
3. Choose English or Urdu as the preferred language. You can still write each book and topic in either language.
4. Use the dark or light theme from the top bar.

## Add study material

Open My Classes.

- Add a class, then open it and add books.
- Open a book. You can add chapters one by one, or choose a Word `.docx` file that is already arranged chapter by chapter. Start each chapter with “Chapter 1: …”, “باب”, or Word Heading 1. Start each topic with “Topic: …”, “موضوع”, or Heading 2. The topics are placed on the matching chapter shelves in the open book. A topic that already has notes is left unchanged.
- If a book has no chapters, the empty state tells you to add one or import a Word file.
- Open a chapter and add topics.
- Use Up and Down to reorder. Archive hides an item without deleting it. Delete moves it to Recently deleted, where Settings can restore it.
- Permanent removal asks you to type DELETE.
- Search from the study page finds topics by title.

Open a topic to edit it. You will see the class, book, chapter, title, language, and reference note.

Type or paste the note. You can also:

1. Choose Record voice and allow the microphone. Speech recognition is already installed with Study Recall.
2. Pause, resume, or stop. The elapsed time stays visible.
3. Choose Transcribe voice. The included speech program turns the recording into text on this computer. Nothing is sent to a server.
4. Correct the transcript. Several recordings can be added to the same note.
5. Choose Listen to hear the note with the speaking voice included with Windows. If that voice is missing for Urdu, the text stays on screen.
6. Add definitions, facts, keywords, formulas, examples, and expected answer points.
7. Choose Save topic.

A draft is saved while you edit. If you return to an unsaved draft, you can use it or keep the last saved note. Tests use the saved note, not an unsaved draft.

The app does not invent facts. If a fact is not in the saved note, it will not be treated as the correct answer.

## Oral test

Choose Go for an Oral Test, then a class, book, and chapter.

Start the test. Topics with saved notes are shuffled. A topic is not repeated in the same test. Skipping a topic records it as skipped.

Explain the topic by speaking or typing. Choose Listen to hear the prompt with the Windows speaking voice. Submit the transcript you approve. The score looks at:

- essential concept coverage, 50%
- factual correctness, 30%
- supporting details and terminology, 20%

Different valid wording can score well. A statement that contradicts the note does not get full marks just because some words match. If a local grading model is not configured, the score is marked approximate. If the answer cannot be graded reliably, it is marked for review instead of given a made-up score.

At the end you see attempted topics, the average, successful and partial recalls, topics that need revision, skipped topics, and the reference note beside each transcript.

## Written test

Choose Go for a Written Test, then a class and book. Tick one or more chapters. Choose a difficulty and review the paper sizes.

A standard paper is 100 marks:

- Section A, fill in the blanks, 30 marks
- Section B, multiple choice, 40 marks
- Section C, short and long questions, 30 marks

If the notes cannot support that many distinct questions, the app says so and offers a smaller paper. It does not invent questions to fill the gap. Any rounding of the percentage split is shown before you start.

The paper is saved as a snapshot. Later edits to your notes do not change an exam that has already been created.

### During the exam

One question is on screen. The countdown starts when that question becomes active.

Default times, which you can change in Settings:

- multiple choice: 45 seconds
- fill in the blank: 60 seconds
- short question: 4 minutes
- long question: 10 minutes

When time runs out, the current answer is saved, an empty answer is marked unanswered, and the next question opens on its own. You do not have to press Next.

Short and long questions can be typed or spoken. If the recording is still being transcribed when the time ends, the next question opens anyway. The result waits until transcription finishes or is recorded as needing review.

Changing the computer clock does not reset the active countdown. If you close the app, only the question that was open is settled from its saved start time. Later questions are not consumed while the app is closed.

## Results and progress

The result shows the student, class, subject, chapters, date, marks, percentage, time, and counts of correct, incorrect, partial, and unanswered answers. Each question shows your answer, the expected answer, the reason for the mark, and a link back to the topic.

Print or save as PDF uses the system print dialog so Urdu text can use your installed fonts. Export HTML saves the same report for printing later.

Progress shows averages, recent scores, and results by class, subject, chapter, and topic. Topics are grouped as needs revision, developing, or well remembered, using the thresholds in Settings. The underlying percentages are shown.

Topics needing revision can start another oral test that contains only those topics. Older results are kept.

## Backup

Settings can:

- back up the SQLite database
- restore a backup after an integrity check
- export and import JSON
- check the database file

JSON import adds copies. It does not wipe the current library. Nothing is uploaded unless you copy a file somewhere yourself.
