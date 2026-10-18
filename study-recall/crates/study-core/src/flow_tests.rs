use crate::exam::{CreateExamRequest, ExamAnswerInput, ExamSync};
use crate::grading::ConceptRef;
use crate::hierarchy::TopicSaveInput;
use crate::speech::{transcribe_wav, ScriptedRunner, SpeechConfig};
use crate::textutil::direction_for_language;
use crate::Database;
use rusqlite::params;
use std::sync::Mutex;

fn concept(kind: &str, label: &str, content: &str) -> ConceptRef {
    ConceptRef {
        kind: kind.into(),
        label: label.into(),
        content: content.into(),
        aliases: String::new(),
    }
}

fn save(db: &mut Database, topic_id: &str, title: &str, reference: &str, concepts: Vec<ConceptRef>) {
    db.save_topic(
        topic_id,
        TopicSaveInput {
            title: title.into(),
            language: "en".into(),
            reference_text: reference.into(),
            concepts,
        },
    )
    .unwrap();
}

#[test]
fn hierarchy_persists_urdu_and_recovers_from_trash() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("study.db");
    let student;
    let class_id;
    let topic_id;
    {
        let mut db = Database::open(&path).unwrap();
        assert_eq!(db.integrity_check().unwrap(), "ok");
        student = db.create_profile("عائشہ", "ur").unwrap();
        assert_eq!(student.preferred_language, "ur");
        class_id = db.create_class(&student.id, "Class 10", "Science").unwrap().id;
        let book = db.create_book(&class_id, "Urdu", "ur").unwrap();
        assert_eq!(book.language, "ur");
        let chapter = db.create_chapter(&book.id, "نظم").unwrap();
        topic_id = db.create_topic(&chapter.id, "نیوران", "ur").unwrap().id;
        db.save_topic(
            &topic_id,
            TopicSaveInput {
                title: "نیوران".into(),
                language: "ur".into(),
                reference_text: "نیوران ایک مخصوص خلیہ ہے جو عصبی پیغام پہنچاتا ہے۔".into(),
                concepts: vec![concept("keyword", "", "نیوران")],
            },
        )
        .unwrap();
        let detail = db.get_topic(&topic_id).unwrap();
        assert_eq!(detail.text_direction, direction_for_language("ur"));
        assert!(detail.reference_text.contains("نیوران"));
        db.soft_delete_class(&class_id).unwrap();
        assert!(db.list_classes(&student.id, false).unwrap().is_empty());
        assert_eq!(db.list_trash(&student.id).unwrap().len(), 1);
        db.restore_class(&class_id).unwrap();
        assert_eq!(db.get_topic(&topic_id).unwrap().title, "نیوران");
        db.reorder_classes(&student.id, &[class_id.clone()]).unwrap();
        let err = db.purge_class(&class_id, "no").unwrap_err().to_string();
        assert!(err.contains("DELETE"));
    }
    let db = Database::open(&path).unwrap();
    let classes = db.list_classes(&student.id, false).unwrap();
    assert_eq!(classes.len(), 1);
    assert_eq!(classes[0].name, "Class 10");
    assert_eq!(classes[0].topic_count, 1);
    assert_eq!(classes[0].studied_topic_count, 1);
    let hit = db.search_topics(&student.id, "نیوران").unwrap();
    assert_eq!(hit.len(), 1);
    assert_eq!(db.get_topic(&topic_id).unwrap().class_name, "Class 10");
}

#[test]
fn oral_shuffle_does_not_repeat_and_paraphrase_scores() {
    let mut db = Database::open_in_memory().unwrap();
    let student = db.create_profile("Ayesha", "en").unwrap();
    let class_id = db.create_class(&student.id, "Class 10", "").unwrap().id;
    let book_id = db.create_book(&class_id, "Biology", "en").unwrap().id;
    let chapter_id = db
        .create_chapter(&book_id, "Chapter 1: Coordination and Control")
        .unwrap()
        .id;
    let neuron = db.create_topic(&chapter_id, "Neuron", "en").unwrap().id;
    let resting = db.create_topic(&chapter_id, "Resting Potential", "en").unwrap().id;
    let action = db.create_topic(&chapter_id, "Action Potential", "en").unwrap().id;
    save(
        &mut db,
        &neuron,
        "Neuron",
        "A neuron is a specialized cell that transmits nerve impulses. A neuron consists of a cell body, dendrites, and an axon.",
        vec![
            concept("definition", "Neuron", "A specialized cell that transmits nerve impulses."),
            concept("keyword", "", "axon"),
            concept("keyword", "", "dendrites"),
            concept("expected_point", "", "transmits nerve impulses"),
        ],
    );
    save(
        &mut db,
        &resting,
        "Resting Potential",
        "The resting potential is the electrical charge difference across the neuron membrane while the cell is at rest. The inside is negative compared with the outside. The sodium-potassium pump maintains this charge.",
        vec![
            concept("keyword", "", "resting potential"),
            concept("fact", "", "The inside is negative compared with the outside."),
            concept("keyword", "", "sodium-potassium pump"),
            concept("expected_point", "", "electrical charge difference across the neuron membrane"),
        ],
    );
    save(
        &mut db,
        &action,
        "Action Potential",
        "An action potential is a rapid change in membrane potential that travels along the axon. Sodium ions enter the neuron during depolarization, and potassium ions leave during repolarization.",
        vec![
            concept("keyword", "", "depolarization"),
            concept("keyword", "", "repolarization"),
            concept("keyword", "", "axon"),
            concept("fact", "", "Sodium ions enter the neuron during depolarization."),
        ],
    );
    let prompt = db.start_oral(&student.id, &chapter_id, Some(42)).unwrap();
    let mut seen = Vec::new();
    let mut session = prompt.session_id.clone();
    let mut current = Some(prompt);
    let answers = [
        ("Neuron", "Neurons are special cells that carry messages through the nervous system. They have a cell body, dendrites, and an axon."),
        ("Resting Potential", "Resting potential is the voltage difference across the neuron membrane. The inside is negative compared with the outside. The sodium-potassium pump keeps this charge."),
        ("Action Potential", "An action potential is a quick change in membrane potential that travels along the axon. Sodium ions enter the neuron during depolarization, and potassium ions leave during repolarization."),
    ];
    while let Some(prompt) = current {
        assert!(!seen.contains(&prompt.topic_id));
        seen.push(prompt.topic_id.clone());
        let transcript = answers
            .iter()
            .find(|(title, _)| *title == prompt.topic_title)
            .map(|(_, text)| *text)
            .unwrap();
        let step = db.submit_oral(&session, transcript).unwrap();
        assert!(step.result.overall.unwrap_or(0.0) >= 70.0, "{:?}", step.result);
        assert_eq!(step.result.method, "approximate-concept-rubric");
        session = prompt.session_id;
        current = if step.finished {
            None
        } else {
            db.get_oral_prompt(&session).unwrap()
        };
    }
    assert_eq!(seen.len(), 3);
    let summary = db.oral_summary(&session).unwrap();
    assert_eq!(summary.attempted, 3);
    assert_eq!(summary.skipped, 0);
    assert!(summary.average_percent.unwrap() >= 70.0);
    assert_eq!(summary.topics.len(), 3);
    let again = db.start_oral(&student.id, &chapter_id, Some(7)).unwrap();
    let skipped = db.skip_oral(&again.session_id).unwrap();
    assert!(skipped.result.skipped);
    assert_ne!(skipped.result.category, "successful");
    let progress = db.progress(&student.id).unwrap();
    assert!(progress.oral_sessions >= 1);
    assert!(progress.needs_revision >= 1 || progress.developing + progress.well_remembered >= 1);
}

#[test]
fn written_exam_timer_marking_backup_and_snapshot() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("study.db");
    let mut db = Database::open(&path).unwrap();
    let student = db.create_profile("Ayesha", "en").unwrap();
    let class_id = db.create_class(&student.id, "Class 10", "").unwrap().id;
    let book_id = db.create_book(&class_id, "Biology", "en").unwrap().id;
    let chapter_a = db.create_chapter(&book_id, "Chapter 1").unwrap().id;
    let chapter_b = db.create_chapter(&book_id, "Chapter 2").unwrap().id;
    let mut chapter_a_topics = Vec::new();
    for i in 0..6 {
        let title = format!("Topic {i}");
        let id = db.create_topic(&chapter_a, &title, "en").unwrap().id;
        let term = format!("Concept{i}");
        let fact = format!("The value of {term} is exactly {i} units in this note.");
        save(
            &mut db,
            &id,
            &title,
            &format!("{title} covers {term} in a complete sentence for study. {fact} A student should remember {term} when explaining {title} today."),
            vec![
                concept("definition", &term, &format!("{term} is the central idea of {title}.")),
                concept("fact", "", &fact),
                concept("keyword", "", &term),
                concept("expected_point", "", &format!("Remember {term} for {title}.")),
            ],
        );
        chapter_a_topics.push(id);
    }
    let other = db.create_topic(&chapter_b, "Outside topic", "en").unwrap().id;
    save(
        &mut db,
        &other,
        "Outside topic",
        "Outside material must never appear in a chapter 1 paper for this test.",
        vec![concept("keyword", "", "OutsideOnlyTerm")],
    );
    let proposal = db
        .propose_exam(&student.id, &book_id, &[chapter_a.clone()], "standard")
        .unwrap();
    assert!(proposal.offers.iter().any(|o| o.feasible));
    let full = proposal.offers.iter().find(|o| o.size_id == "full").unwrap();
    assert!(!full.feasible);
    let chosen = proposal
        .offers
        .iter()
        .filter(|o| o.feasible)
        .max_by_key(|o| o.total_marks)
        .unwrap()
        .clone();
    let created = db
        .create_exam(CreateExamRequest {
            student_id: student.id.clone(),
            book_id: book_id.clone(),
            chapter_ids: vec![chapter_a.clone()],
            difficulty: "standard".into(),
            size_id: chosen.size_id.clone(),
            seed: Some(42),
        })
        .unwrap();
    let passages: Vec<(i64, String, String)> = {
        let mut stmt = db
            .conn
            .prepare("SELECT position, source_topic_id, source_passage, correct_answer FROM written_exam_questions WHERE exam_id = ?1")
            .unwrap();
        let rows = stmt
            .query_map(params![created.exam_id], |row| {
                Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?))
            })
            .unwrap();
        rows.map(|r| {
            let (pos, topic, passage, _answer) = r.unwrap();
            assert!(chapter_a_topics.contains(&topic), "{topic}");
            assert!(!passage.contains("OutsideOnlyTerm"));
            (pos, topic, passage)
        })
        .collect()
    };
    assert!(!passages.is_empty());
    let before = db.question_source_passage(&created.exam_id, 0).unwrap();
    db.save_topic(
        &chapter_a_topics[0],
        TopicSaveInput {
            title: "Topic 0".into(),
            language: "en".into(),
            reference_text: "Changed after the exam was created.".into(),
            concepts: vec![concept("keyword", "", "Changed")],
        },
    )
    .unwrap();
    assert_eq!(db.question_source_passage(&created.exam_id, 0).unwrap(), before);

    let view = db.start_exam(&created.exam_id, 1_000_000).unwrap();
    let generation = view.timer_generation;
    let question_id = view.question.as_ref().unwrap().id.clone();
    let duration = view.duration_ms;
    db.save_exam_draft(&created.exam_id, &question_id, "kept answer", None)
        .unwrap();
    let anchor = db.stored_answer(&created.exam_id, 0).unwrap();
    assert_eq!(anchor.active_started_wall_ms, Some(1_000_000));
    assert_eq!(anchor.timer_generation, generation);
    let expired = db
        .sync_exam(
            &created.exam_id,
            ExamSync {
                wall_now_ms: 1_000_000,
                timer_generation: Some(generation),
                monotonic_elapsed_ms: Some(duration),
            },
        )
        .unwrap();
    assert_eq!(expired.current_index, 1);
    let stored = db.stored_answer(&created.exam_id, 0).unwrap();
    assert!(stored.locked);
    assert!(stored.timed_out);
    assert_eq!(stored.response_text, "kept answer");
    assert_eq!(stored.status, "answered");
    let stale = db
        .sync_exam(
            &created.exam_id,
            ExamSync {
                wall_now_ms: 1_000_000 + duration as i64,
                timer_generation: Some(generation),
                monotonic_elapsed_ms: Some(duration + 5_000),
            },
        )
        .unwrap();
    assert_eq!(stale.current_index, 1, "a stale timer must not skip the next question");
    let err = db
        .submit_exam_answer(
            &created.exam_id,
            &question_id,
            ExamAnswerInput {
                response_text: "second".into(),
                selected_option: None,
                pending_transcription: false,
            },
            1_000_000,
        )
        .unwrap_err()
        .to_string();
    assert!(err.contains("locked"));

    // Answer every remaining question from the saved key, including the timed-out first one as already stored.
    let keys: Vec<(String, i64, String, String, String)> = {
        let mut stmt = db.conn.prepare(
            "SELECT q.id, q.position, q.question_type, q.correct_answer, IFNULL(q.options_json, '[]')
             FROM written_exam_questions q WHERE q.exam_id = ?1 ORDER BY q.position",
        ).unwrap();
        stmt.query_map(params![created.exam_id], |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?))
        }).unwrap().collect::<Result<Vec<_>, _>>().unwrap()
    };
    for (id, position, kind, correct, _options) in keys {
        if position == 0 {
            continue;
        }
        let view = db
            .sync_exam(
                &created.exam_id,
                ExamSync { wall_now_ms: 1_000_000, timer_generation: None, monotonic_elapsed_ms: None },
            )
            .unwrap();
        if view.status != "in_progress" {
            break;
        }
        let active = view.question.unwrap();
        assert_eq!(active.id, id);
        let input = if kind == "mcq" {
            ExamAnswerInput { response_text: String::new(), selected_option: Some(correct), pending_transcription: false }
        } else {
            ExamAnswerInput { response_text: correct, selected_option: None, pending_transcription: false }
        };
        db.submit_exam_answer(&created.exam_id, &active.id, input, 1_000_000).unwrap();
    }
    let result = db.finalize_exam(&created.exam_id).unwrap();
    assert_eq!(result.student_name, "Ayesha");
    assert_eq!(result.class_name, "Class 10");
    assert_eq!(result.book_title, "Biology");
    assert!(result.chapter_titles.iter().any(|t| t.contains("Chapter 1")));
    assert!(result.max_marks > 0);
    assert!(result.obtained_marks > 0.0);
    let summed: f64 = result.questions.iter().filter_map(|q| q.awarded).sum();
    assert!((summed - result.obtained_marks).abs() < 0.2);
    assert!(result.questions.iter().all(|q| !q.source_topic_id.is_empty()));
    assert!(result.questions.iter().any(|q| q.question_type == "mcq" && q.awarded == Some(q.max_marks as f64)));
    let html = db.exam_html(&created.exam_id).unwrap();
    assert!(html.contains("Ayesha"));
    assert!(html.contains("Class 10"));
    let progress = db.progress(&student.id).unwrap();
    assert_eq!(progress.written_exams, 1);
    assert!(!progress.recent_written.is_empty());

    let backup = dir.path().join("backup.db");
    db.backup_to(&backup).unwrap();
    db.create_class(&student.id, "Should vanish", "").unwrap();
    db.restore_from(&backup).unwrap();
    let names: Vec<_> = db.list_classes(&student.id, true).unwrap().into_iter().map(|c| c.name).collect();
    assert!(names.contains(&"Class 10".to_string()));
    assert!(!names.iter().any(|n| n == "Should vanish"));
    assert_eq!(db.get_exam_result(&created.exam_id).unwrap().student_name, "Ayesha");

    let exported = db.export_json().unwrap();
    let mut other = Database::open_in_memory().unwrap();
    let count = other.import_json(&exported).unwrap();
    assert!(count > 0);
    let imported = other.list_profiles().unwrap();
    assert!(imported.iter().any(|p| p.display_name == "Ayesha"));
}

#[test]
fn speech_pipeline_saves_a_transcript_from_test_audio() {
    let mut db = Database::open_in_memory().unwrap();
    let student = db.create_profile("Ayesha", "en").unwrap();
    let class_id = db.create_class(&student.id, "Class 10", "").unwrap().id;
    let book_id = db.create_book(&class_id, "Biology", "en").unwrap().id;
    let chapter_id = db.create_chapter(&book_id, "Chapter 1").unwrap().id;
    let topic_id = db.create_topic(&chapter_id, "Neuron", "en").unwrap().id;
    let dir = tempfile::tempdir().unwrap();
    let binary = dir.path().join("whisper-cli");
    let model = dir.path().join("ggml-small.bin");
    std::fs::write(&binary, b"bin").unwrap();
    std::fs::write(&model, b"model").unwrap();
    let runner = ScriptedRunner {
        stdout: "A neuron is a specialized cell.".into(),
        status: 0,
        calls: Mutex::new(vec![]),
    };
    let wav = crate::speech::synthesize_test_wav(&[0, 400, -400, 20, 0], 16_000);
    let outcome = transcribe_wav(
        &runner,
        &SpeechConfig {
            binary_path: binary.display().to_string(),
            model_path: model.display().to_string(),
        },
        &wav,
        "en",
        &dir.path().join("work"),
        false,
    );
    assert!(outcome.ok, "{}", outcome.error_message);
    db.save_topic(
        &topic_id,
        TopicSaveInput {
            title: "Neuron".into(),
            language: "en".into(),
            reference_text: outcome.text.clone(),
            concepts: vec![concept("keyword", "", "neuron")],
        },
    )
    .unwrap();
    assert_eq!(db.get_topic(&topic_id).unwrap().reference_text, "A neuron is a specialized cell.");
    let (ready, message) = crate::speech::assess_whisper("", "");
    assert!(!ready);
    assert!(message.contains("type"));
}

#[test]
fn objective_wrong_answer_scores_zero() {
    let mut db = Database::open_in_memory().unwrap();
    let student = db.create_profile("Ayesha", "en").unwrap();
    let class_id = db.create_class(&student.id, "Class 10", "").unwrap().id;
    let book_id = db.create_book(&class_id, "Biology", "en").unwrap().id;
    let chapter_id = db.create_chapter(&book_id, "Chapter 1").unwrap().id;
    for i in 0..4 {
        let title = format!("Topic {i}");
        let id = db.create_topic(&chapter_id, &title, "en").unwrap().id;
        let term = format!("Concept{i}");
        let fact = format!("The value of {term} is exactly {i} units in this note.");
        save(
            &mut db,
            &id,
            &title,
            &format!("{title} covers {term} in a complete sentence for study. {fact} A student should remember {term} when explaining {title} today."),
            vec![
                concept("definition", &term, &format!("{term} is the central idea of {title}.")),
                concept("fact", "", &fact),
                concept("keyword", "", &term),
                concept("expected_point", "", &format!("Remember {term} for {title}.")),
            ],
        );
    }
    let proposal = db.propose_exam(&student.id, &book_id, &[chapter_id.clone()], "easy").unwrap();
    let size = proposal.offers.iter().find(|o| o.feasible).unwrap().size_id.clone();
    let created = db.create_exam(CreateExamRequest {
        student_id: student.id,
        book_id,
        chapter_ids: vec![chapter_id],
        difficulty: "easy".into(),
        size_id: size,
        seed: Some(3),
    }).unwrap();
    db.start_exam(&created.exam_id, 5_000).unwrap();
    loop {
        let view = db.sync_exam(&created.exam_id, ExamSync { wall_now_ms: 5_000, timer_generation: None, monotonic_elapsed_ms: None }).unwrap();
        if view.status != "in_progress" {
            break;
        }
        let question = view.question.unwrap();
        let input = if question.question_type == "mcq" {
            let correct: String = db.conn.query_row(
                "SELECT correct_answer FROM written_exam_questions WHERE id = ?1",
                params![question.id],
                |row| row.get(0),
            ).unwrap();
            let wrong = question
                .options
                .iter()
                .map(|o| o.id.clone())
                .find(|id| !id.eq_ignore_ascii_case(&correct))
                .unwrap();
            ExamAnswerInput { response_text: String::new(), selected_option: Some(wrong), pending_transcription: false }
        } else if question.question_type == "fib" {
            ExamAnswerInput { response_text: "dendrite".into(), selected_option: None, pending_transcription: false }
        } else {
            ExamAnswerInput { response_text: "I do not remember this topic.".into(), selected_option: None, pending_transcription: false }
        };
        db.submit_exam_answer(&created.exam_id, &question.id, input, 5_000).unwrap();
    }
    let result = db.finalize_exam(&created.exam_id).unwrap();
    let mcq = result.questions.iter().find(|q| q.question_type == "mcq").unwrap();
    assert_eq!(mcq.awarded, Some(0.0));
    let fib = result.questions.iter().find(|q| q.question_type == "fib").unwrap();
    assert_eq!(fib.awarded, Some(0.0));
}

