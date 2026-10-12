# Limits of speech recognition and automated grading

Study Recall never pretends that a missing local model is a cloud service. If whisper.cpp or llama.cpp is not configured, Settings and the transcription result say so, and the rest of the app keeps working.

## Speech to text

- Transcription runs only through a local whisper.cpp program and a model file you select.
- English and Urdu depend on that model. An English-only model is rejected for Urdu.
- Tiny and base models are a weak match for Urdu. The app warns you to read the transcript before saving.
- Recognition mistakes are normal. The transcript is editable, and the saved note is whatever you approve.
- Long explanations should be recorded in segments and combined. A single recording larger than 40 MB is refused.
- The microphone can be denied. Typing and pasting are always available.
- Audio is removed after transcription unless you explicitly keep recordings.
- No audio or transcript is sent to an external service by this application.

## Oral and descriptive marks

The built-in marker compares your answer with the saved note:

- It accepts different wording when the same content words and concepts are present.
- It treats negation and direct contradictions as incorrect, so a keyword match is not enough for full marks.
- It does not grade grammar, accent, or harmless spelling beyond a narrow spelling check for fill-in-the-blank answers.
- Fill-in-the-blank spelling tolerance does not accept a different scientific term.
- Multiple choice and blank answers are marked against the stored correct answer and its listed alternatives. A wrong or blank answer scores zero.
- Short and long answers use factual correctness 40%, required concept coverage 40%, and completeness 20%.

These scores are estimates. They can miss a correct paraphrase that shares too few words with the note, and they can be generous when many important words appear in the wrong relationship.

If llama.cpp and a model are configured, the app may ask that local model for a second estimate. The result is still labeled as a model estimate. If the model output cannot be parsed, or the answer is too uncertain, the item is marked for review and is not given an invented confident mark.

Automated marks are not a teacher’s judgment. Use them to find what to revise, then read the reference note beside the answer.

## Question generation

Questions are built from sentences, terms, and reference items in the saved notes. A question without support in that material is not kept. The app will not add filler questions to reach 100 marks.

Distractors are drawn from other terms in the selected chapters. If the notes are too short to make four distinct choices or a useful blank, that question is skipped and a smaller paper is offered.

Difficulty changes which supported questions are preferred. It does not create facts that you did not enter.
