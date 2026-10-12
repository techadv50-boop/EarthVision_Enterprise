use std::collections::BTreeMap;

use chrono::DateTime;
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

use crate::db::{new_id, not_found, now_ts, Database, RECOVERY_POLICY};
use crate::error::{AppError, AppResult};
use crate::grading::{grade_descriptive, grade_fib, grade_mcq, ConceptRef};
use crate::questions::{build_paper, propose, McqOption, PaperOffer, Proposal, TopicMaterial};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateExamRequest {
    pub student_id: String,
    pub book_id: String,
    pub chapter_ids: Vec<String>,
    pub difficulty: String,
    pub size_id: String,
    pub seed: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreatedExam {
    pub exam_id: String,
    pub instructions: String,
    pub offer: PaperOffer,
    pub question_count: usize,
    pub recovery_policy: String,
    pub class_name: String,
    pub book_title: String,
    pub chapter_titles: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamQuestionView {
    pub id: String,
    pub position: usize,
    pub question_type: String,
    pub prompt: String,
    pub options: Vec<McqOption>,
    pub max_marks: i64,
    pub draft_text: String,
    pub draft_option: Option<String>,
    pub locked: bool,
    pub duration_ms: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamView {
    pub exam_id: String,
    pub status: String,
    pub current_index: usize,
    pub total_questions: usize,
    pub question: Option<ExamQuestionView>,
    pub remaining_ms: u64,
    pub duration_ms: u64,
    pub timer_generation: i64,
    pub started_wall_ms: Option<i64>,
    pub progress: f64,
    pub pending_transcription: usize,
    pub recovery_policy: String,
    pub total_marks: i64,
    pub weighting_note: String,
    pub instructions: String,
    pub class_name: String,
    pub book_title: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamSync {
    pub wall_now_ms: i64,
    pub timer_generation: Option<i64>,
    pub monotonic_elapsed_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamAnswerInput {
    pub response_text: String,
    pub selected_option: Option<String>,
    pub pending_transcription: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StoredAnswer {
    pub position: i64,
    pub response_text: String,
    pub selected_option: Option<String>,
    pub status: String,
    pub timed_out: bool,
    pub locked: bool,
    pub timer_generation: i64,
    pub active_started_wall_ms: Option<i64>,
    pub active_duration_ms: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct QuestionReview {
    pub position: i64,
    pub question_type: String,
    pub prompt: String,
    pub options: Vec<McqOption>,
    pub student_answer: String,
    pub correct_answer: String,
    pub awarded: Option<f64>,
    pub max_marks: i64,
    pub explanation: String,
    pub source_topic_id: String,
    pub topic_title: String,
    pub confidence: String,
    pub method: String,
    pub covered: Vec<String>,
    pub missing: Vec<String>,
    pub incorrect: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SectionScore {
    pub name: String,
    pub awarded: f64,
    pub max_marks: i64,
    pub correct: i64,
    pub partial: i64,
    pub incorrect: i64,
    pub unanswered: i64,
    pub review: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamResult {
    pub exam_id: String,
    pub student_name: String,
    pub class_name: String,
    pub book_title: String,
    pub chapter_titles: Vec<String>,
    pub taken_at: String,
    pub obtained_marks: f64,
    pub max_marks: i64,
    pub percentage: f64,
    pub time_taken_ms: i64,
    pub correct_count: i64,
    pub partial_count: i64,
    pub incorrect_count: i64,
    pub unanswered_count: i64,
    pub review_count: i64,
    pub sections: Vec<SectionScore>,
    pub questions: Vec<QuestionReview>,
    pub weighting_note: String,
    pub grading_note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActiveExam {
    pub exam_id: String,
    pub status: String,
    pub class_name: String,
    pub book_title: String,
    pub created_at: String,
    pub question_count: i64,
    pub current_index: i64,
}

impl Database {
    pub fn propose_exam(
        &self,
        student_id: &str,
        book_id: &str,
        chapter_ids: &[String],
        difficulty: &str,
    ) -> AppResult<Proposal> {
        let topics = self.materials_for(student_id, book_id, chapter_ids)?;
        Ok(propose(&topics, normalize_difficulty(difficulty)?))
    }

    pub fn create_exam(&mut self, request: CreateExamRequest) -> AppResult<CreatedExam> {
        let difficulty = normalize_difficulty(&request.difficulty)?;
        let topics = self.materials_for(&request.student_id, &request.book_id, &request.chapter_ids)?;
        let seed = request.seed.unwrap_or_else(rand::random) & (i64::MAX as u64);
        let (offer, questions) = build_paper(&topics, difficulty, &request.size_id, seed)?;
        let (class_id, class_name, book_title) = self.book_context(&request.book_id)?;
        let chapter_titles = self.chapter_titles(&request.chapter_ids)?;
        let settings = self.get_settings()?;
        let exam_id = new_id();
        let ts = now_ts();
        let instructions = format!(
            "This examination uses only your saved notes from the selected chapters. One question is shown at a time. When the timer ends, the current answer is saved and the next question opens. A locked question stays locked. {note} {}",
            offer.rounding_note,
            note = if offer.rounding_note.to_lowercase().contains("approximate") {
                ""
            } else {
                "Short and long answers receive an estimated score."
            }
        );
        let grading_line = "Short and long answers are estimated. If a local language model is configured, its score is labeled as a model estimate. Otherwise the approximate concept rubric is labeled on the result.";
        let instructions = format!("{instructions} {grading_line}");
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO written_exams
             (id, student_id, class_id, book_id, chapter_ids_json, difficulty, paper_size, status,
              current_index, timer_generation, seed, total_marks, weighting_note, instructions,
              recovery_policy, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'ready', 0, 0, ?8, ?9, ?10, ?11, ?12, ?13)",
            params![
                exam_id,
                request.student_id,
                class_id,
                request.book_id,
                serde_json::to_string(&request.chapter_ids).unwrap_or_else(|_| "[]".into()),
                difficulty,
                offer.size_id,
                seed as i64,
                offer.total_marks,
                offer.rounding_note,
                instructions,
                RECOVERY_POLICY,
                ts
            ],
        )?;
        for (position, question) in questions.iter().enumerate() {
            let qid = new_id();
            let duration = duration_for(&question.question_type, &settings);
            let rubric = serde_json::json!({
                "points": question.rubric_points,
                "alternatives": question.alternatives,
                "topicIds": question.topic_ids,
            });
            tx.execute(
                "INSERT INTO written_exam_questions
                 (id, exam_id, position, question_type, prompt, options_json, correct_answer, rubric_json,
                  max_marks, source_topic_id, source_passage, difficulty, duration_ms, locked)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, 0)",
                params![
                    qid,
                    exam_id,
                    position as i64,
                    question.question_type,
                    question.prompt,
                    serde_json::to_string(&question.options).unwrap_or_else(|_| "[]".into()),
                    question.correct_answer,
                    rubric.to_string(),
                    question.max_marks,
                    question.source_topic_id,
                    question.source_passage,
                    question.difficulty,
                    duration
                ],
            )?;
            tx.execute(
                "INSERT INTO written_exam_answers (id, question_id, status) VALUES (?1, ?2, 'unanswered')",
                params![new_id(), qid],
            )?;
        }
        tx.commit()?;
        Ok(CreatedExam {
            exam_id,
            instructions,
            question_count: questions.len(),
            recovery_policy: RECOVERY_POLICY.into(),
            class_name,
            book_title,
            chapter_titles,
            offer,
        })
    }

    pub fn start_exam(&mut self, exam_id: &str, wall_now_ms: i64) -> AppResult<ExamView> {
        let status = self.exam_status(exam_id)?;
        if status == "in_progress" || status == "awaiting_transcription" || status == "completed" {
            return self.sync_exam(exam_id, ExamSync { wall_now_ms, timer_generation: None, monotonic_elapsed_ms: None });
        }
        if status != "ready" {
            return Err(AppError::Conflict("This examination cannot be started.".into()));
        }
        let duration = self.question_duration(exam_id, 0)?;
        let ts = now_ts();
        self.conn.execute(
            "UPDATE written_exams
             SET status = 'in_progress', current_index = 0, timer_generation = 1,
                 active_started_wall_ms = ?1, active_duration_ms = ?2, started_at = ?3
             WHERE id = ?4 AND status = 'ready'",
            params![wall_now_ms, duration, ts, exam_id],
        )?;
        self.exam_view(exam_id, wall_now_ms)
    }

    pub fn sync_exam(&mut self, exam_id: &str, sync: ExamSync) -> AppResult<ExamView> {
        self.expire_if_due(exam_id, &sync)?;
        self.exam_view(exam_id, sync.wall_now_ms)
    }

    pub fn save_exam_draft(
        &mut self,
        exam_id: &str,
        question_id: &str,
        draft_text: &str,
        draft_option: Option<String>,
    ) -> AppResult<ExamView> {
        let started = self.timer_anchor(exam_id)?;
        let changed = self.conn.execute(
            "UPDATE written_exam_answers
             SET draft_text = ?1, draft_option = ?2
             WHERE question_id = ?3
               AND question_id IN (
                    SELECT id FROM written_exam_questions WHERE id = ?3 AND exam_id = ?4 AND locked = 0
               )",
            params![draft_text, draft_option, question_id, exam_id],
        )?;
        if changed == 0 {
            return Err(AppError::Conflict("This question is locked, so the draft was left unchanged.".into()));
        }
        let after = self.timer_anchor(exam_id)?;
        if after != started {
            return Err(AppError::Conflict("Saving a draft changed the timer.".into()));
        }
        let wall = started.0.unwrap_or(0);
        self.exam_view(exam_id, wall)
    }

    pub fn submit_exam_answer(
        &mut self,
        exam_id: &str,
        question_id: &str,
        input: ExamAnswerInput,
        wall_now_ms: i64,
    ) -> AppResult<ExamView> {
        let status_name = if input.pending_transcription {
            "pending_transcription"
        } else {
            "answered"
        };
        self.finish_question(
            exam_id,
            question_id,
            status_name,
            input.response_text.trim(),
            input.selected_option.as_deref(),
            false,
            wall_now_ms,
        )?;
        self.exam_view(exam_id, wall_now_ms)
    }

    pub fn resolve_transcription(
        &mut self,
        exam_id: &str,
        question_id: &str,
        transcript: &str,
        failed: bool,
    ) -> AppResult<ExamView> {
        let status = if failed || transcript.trim().is_empty() && failed {
            "transcription_failed"
        } else if transcript.trim().is_empty() {
            "transcription_failed"
        } else {
            "answered"
        };
        let changed = self.conn.execute(
            "UPDATE written_exam_answers
             SET response_text = ?1, status = ?2, submitted_at = ?3
             WHERE question_id = ?4 AND status = 'pending_transcription'
               AND question_id IN (SELECT id FROM written_exam_questions WHERE exam_id = ?5)",
            params![transcript.trim(), status, now_ts(), question_id, exam_id],
        )?;
        if changed == 0 {
            return Err(AppError::Conflict("That answer is not waiting for transcription.".into()));
        }
        let wall = self.timer_anchor(exam_id)?.0.unwrap_or(0);
        self.exam_view(exam_id, wall)
    }

    pub fn finalize_exam(&mut self, exam_id: &str) -> AppResult<ExamResult> {
        if self.result_exists(exam_id)? {
            return self.get_exam_result(exam_id);
        }
        let pending: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM written_exam_answers a
             JOIN written_exam_questions q ON q.id = a.question_id
             WHERE q.exam_id = ?1 AND a.status = 'pending_transcription'",
            params![exam_id],
            |row| row.get(0),
        )?;
        if pending > 0 {
            self.conn.execute(
                "UPDATE written_exams SET status = 'awaiting_transcription' WHERE id = ?1 AND status != 'completed'",
                params![exam_id],
            )?;
            return Err(AppError::Conflict(format!(
                "{pending} answer(s) are still being transcribed. The result will be ready when transcription finishes."
            )));
        }
        let status = self.exam_status(exam_id)?;
        if status == "ready" {
            return Err(AppError::Conflict("Start the examination before marking it.".into()));
        }
        let result = self.grade_all(exam_id)?;
        let section_json = serde_json::to_string(&result.sections).unwrap_or_else(|_| "[]".into());
        let detail_json = serde_json::to_string(&result.questions).unwrap_or_else(|_| "[]".into());
        let ts = now_ts();
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO written_exam_results
             (id, exam_id, obtained_marks, graded_max_marks, paper_max_marks, percentage,
              percentage_if_review_is_zero, correct_count, incorrect_count, partial_count,
              unanswered_count, review_count, section_json, detail_json, time_taken_ms, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
            params![
                new_id(),
                exam_id,
                result.obtained_marks,
                result.max_marks as f64,
                result.max_marks,
                result.percentage,
                result.correct_count,
                result.incorrect_count,
                result.partial_count,
                result.unanswered_count,
                result.review_count,
                section_json,
                detail_json,
                result.time_taken_ms,
                ts
            ],
        )?;
        tx.execute(
            "UPDATE written_exams SET status = 'completed', completed_at = ?1 WHERE id = ?2",
            params![ts, exam_id],
        )?;
        for question in &result.questions {
            tx.execute(
                "UPDATE written_exam_answers
                 SET awarded_marks = ?1, grading_method = ?2, grading_confidence = ?3, grading_json = ?4
                 WHERE question_id = (
                    SELECT id FROM written_exam_questions WHERE exam_id = ?5 AND position = ?6
                 )",
                params![
                    question.awarded,
                    question.method,
                    question.confidence,
                    serde_json::json!({
                        "explanation": question.explanation,
                        "covered": question.covered,
                        "missing": question.missing,
                        "incorrect": question.incorrect,
                    }).to_string(),
                    exam_id,
                    question.position
                ],
            )?;
        }
        tx.commit()?;
        self.record_written_revision(exam_id, &result)?;
        self.get_exam_result(exam_id)
    }

    pub fn get_exam_result(&self, exam_id: &str) -> AppResult<ExamResult> {
        let row = self.conn.query_row(
            "SELECT r.obtained_marks, r.paper_max_marks, r.percentage, r.correct_count, r.incorrect_count,
                    r.partial_count, r.unanswered_count, r.review_count, r.section_json, r.detail_json,
                    r.time_taken_ms, r.created_at, e.weighting_note, p.display_name, c.name, b.title, e.chapter_ids_json
             FROM written_exam_results r
             JOIN written_exams e ON e.id = r.exam_id
             JOIN student_profiles p ON p.id = e.student_id
             JOIN classes c ON c.id = e.class_id
             JOIN books b ON b.id = e.book_id
             WHERE e.id = ?1",
            params![exam_id],
            |row| {
                Ok((
                    row.get::<_, f64>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, f64>(2)?,
                    row.get::<_, i64>(3)?,
                    row.get::<_, i64>(4)?,
                    row.get::<_, i64>(5)?,
                    row.get::<_, i64>(6)?,
                    row.get::<_, i64>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, String>(9)?,
                    row.get::<_, i64>(10)?,
                    row.get::<_, String>(11)?,
                    row.get::<_, String>(12)?,
                    row.get::<_, String>(13)?,
                    row.get::<_, String>(14)?,
                    row.get::<_, String>(15)?,
                    row.get::<_, String>(16)?,
                ))
            },
        ).map_err(|err| not_found(err, "That result was not found."))?;
        let chapter_ids: Vec<String> = serde_json::from_str(&row.16).unwrap_or_default();
        let chapter_titles = self.chapter_titles(&chapter_ids).unwrap_or_default();
        let sections = serde_json::from_str(&row.8).unwrap_or_default();
        let questions = serde_json::from_str(&row.9).unwrap_or_default();
        let grading_note = if row.7 > 0 {
            format!("{} answer(s) need review and are counted as zero in the percentage. Automatic descriptive scores are estimates.", row.7)
        } else {
            "Automatic descriptive scores are estimates. Objective questions are marked from the saved answers.".into()
        };
        Ok(ExamResult {
            exam_id: exam_id.into(),
            student_name: row.13,
            class_name: row.14,
            book_title: row.15,
            chapter_titles,
            taken_at: row.11,
            obtained_marks: row.0,
            max_marks: row.1,
            percentage: row.2,
            time_taken_ms: row.10,
            correct_count: row.3,
            partial_count: row.5,
            incorrect_count: row.4,
            unanswered_count: row.6,
            review_count: row.7,
            sections,
            questions,
            weighting_note: row.12,
            grading_note,
        })
    }

    pub fn exam_html(&self, exam_id: &str) -> AppResult<String> {
        let result = self.get_exam_result(exam_id)?;
        Ok(render_result_html(&result))
    }

    pub fn list_active_exams(&self, student_id: &str) -> AppResult<Vec<ActiveExam>> {
        let mut stmt = self.conn.prepare(
            "SELECT e.id, e.status, c.name, b.title, e.created_at, e.current_index,
                    (SELECT COUNT(*) FROM written_exam_questions q WHERE q.exam_id = e.id)
             FROM written_exams e
             JOIN classes c ON c.id = e.class_id
             JOIN books b ON b.id = e.book_id
             WHERE e.student_id = ?1 AND e.status IN ('ready', 'in_progress', 'awaiting_transcription')
             ORDER BY e.created_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(ActiveExam {
                exam_id: row.get(0)?,
                status: row.get(1)?,
                class_name: row.get(2)?,
                book_title: row.get(3)?,
                created_at: row.get(4)?,
                current_index: row.get(5)?,
                question_count: row.get(6)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn stored_answer(&self, exam_id: &str, position: i64) -> AppResult<StoredAnswer> {
        let anchor = self.timer_anchor(exam_id)?;
        self.conn.query_row(
            "SELECT q.position, a.response_text, a.selected_option, a.status, a.timed_out, q.locked
             FROM written_exam_questions q
             JOIN written_exam_answers a ON a.question_id = q.id
             WHERE q.exam_id = ?1 AND q.position = ?2",
            params![exam_id, position],
            |row| {
                Ok(StoredAnswer {
                    position: row.get(0)?,
                    response_text: row.get(1)?,
                    selected_option: row.get(2)?,
                    status: row.get(3)?,
                    timed_out: row.get::<_, i64>(4)? == 1,
                    locked: row.get::<_, i64>(5)? == 1,
                    timer_generation: anchor.1,
                    active_started_wall_ms: anchor.0,
                    active_duration_ms: anchor.2,
                })
            },
        ).map_err(|err| not_found(err, "That question was not found."))
    }

    pub fn question_source_passage(&self, exam_id: &str, position: i64) -> AppResult<String> {
        self.conn.query_row(
            "SELECT source_passage FROM written_exam_questions WHERE exam_id = ?1 AND position = ?2",
            params![exam_id, position],
            |row| row.get(0),
        ).map_err(|err| not_found(err, "That question was not found."))
    }

    fn expire_if_due(&mut self, exam_id: &str, sync: &ExamSync) -> AppResult<bool> {
        let (status, index, generation, started, duration) = self.timer_row(exam_id)?;
        if status != "in_progress" {
            return Ok(false);
        }
        let Some(started) = started else { return Ok(false); };
        let duration = duration.unwrap_or(0).max(0) as u64;
        let wall_elapsed = sync.wall_now_ms.saturating_sub(started).max(0) as u64;
        let elapsed = match (sync.timer_generation, sync.monotonic_elapsed_ms) {
            (Some(gen), Some(mono)) if gen == generation => mono,
            (None, None) => wall_elapsed,
            _ => return Ok(false),
        };
        if elapsed < duration {
            return Ok(false);
        }
        let question_id: String = self.conn.query_row(
            "SELECT id FROM written_exam_questions WHERE exam_id = ?1 AND position = ?2",
            params![exam_id, index],
            |row| row.get(0),
        )?;
        let (draft_text, draft_option): (String, Option<String>) = self.conn.query_row(
            "SELECT draft_text, draft_option FROM written_exam_answers WHERE question_id = ?1",
            params![question_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        let has_answer = !draft_text.trim().is_empty() || draft_option.as_deref().unwrap_or("").trim() != "";
        let status_name = if has_answer { "answered" } else { "unanswered" };
        match self.finish_question(
            exam_id,
            &question_id,
            status_name,
            draft_text.trim(),
            draft_option.as_deref(),
            true,
            sync.wall_now_ms,
        ) {
            Err(AppError::Conflict(message)) if message.contains("already locked") => Ok(false),
            other => other,
        }
    }

    fn finish_question(
        &mut self,
        exam_id: &str,
        question_id: &str,
        status_name: &str,
        response_text: &str,
        selected_option: Option<&str>,
        timed_out: bool,
        wall_now_ms: i64,
    ) -> AppResult<bool> {
        let (exam_status, index, generation, _, _) = self.timer_row(exam_id)?;
        if exam_status != "in_progress" {
            return Err(AppError::Conflict("This examination is not accepting answers.".into()));
        }
        let (position, locked, duration): (i64, i64, i64) = self.conn.query_row(
            "SELECT position, locked, duration_ms FROM written_exam_questions WHERE id = ?1 AND exam_id = ?2",
            params![question_id, exam_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        ).map_err(|err| not_found(err, "That question was not found."))?;
        if locked == 1 {
            return Err(AppError::Conflict("This question is already locked.".into()));
        }
        if position != index {
            return Err(AppError::Conflict("Only the active question can be submitted.".into()));
        }
        let total: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM written_exam_questions WHERE exam_id = ?1",
            params![exam_id],
            |row| row.get(0),
        )?;
        let next = index + 1;
        let next_duration = if next < total {
            Some(self.question_duration(exam_id, next)?)
        } else {
            None
        };
        let tx = self.conn.transaction()?;
        let locked_now = tx.execute(
            "UPDATE written_exam_questions SET locked = 1 WHERE id = ?1 AND locked = 0",
            params![question_id],
        )?;
        if locked_now == 0 {
            return Err(AppError::Conflict("This question is already locked.".into()));
        }
        tx.execute(
            "UPDATE written_exam_answers
             SET response_text = ?1, selected_option = ?2, status = ?3, timed_out = ?4, submitted_at = ?5,
                 draft_text = ?1, draft_option = ?2
             WHERE question_id = ?6",
            params![
                response_text,
                selected_option,
                status_name,
                if timed_out { 1 } else { 0 },
                now_ts(),
                question_id
            ],
        )?;
        if let Some(next_duration) = next_duration {
            tx.execute(
                "UPDATE written_exams
                 SET current_index = ?1, timer_generation = ?2, active_started_wall_ms = ?3, active_duration_ms = ?4
                 WHERE id = ?5",
                params![next, generation + 1, wall_now_ms, next_duration, exam_id],
            )?;
        } else {
            tx.execute(
                "UPDATE written_exams
                 SET current_index = ?1, status = 'awaiting_transcription', active_started_wall_ms = NULL, active_duration_ms = NULL
                 WHERE id = ?2",
                params![next, exam_id],
            )?;
        }
        tx.commit()?;
        let _ = duration;
        Ok(true)
    }

    fn grade_all(&self, exam_id: &str) -> AppResult<ExamResult> {
        let mut stmt = self.conn.prepare(
            "SELECT q.position, q.question_type, q.prompt, q.options_json, q.correct_answer, q.rubric_json,
                    q.max_marks, q.source_topic_id, q.source_passage, t.title,
                    a.response_text, a.selected_option, a.status
             FROM written_exam_questions q
             JOIN written_exam_answers a ON a.question_id = q.id
             LEFT JOIN topics t ON t.id = q.source_topic_id
             WHERE q.exam_id = ?1
             ORDER BY q.position",
        )?;
        let rows = stmt.query_map(params![exam_id], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, String>(8)?,
                row.get::<_, Option<String>>(9)?,
                row.get::<_, String>(10)?,
                row.get::<_, Option<String>>(11)?,
                row.get::<_, String>(12)?,
            ))
        })?;
        let mut loaded = Vec::new();
        for row in rows {
            loaded.push(row?);
        }
        let confusion: Vec<String> = loaded
            .iter()
            .filter(|row| row.1 == "fib")
            .map(|row| row.4.clone())
            .collect();
        let mut reviews = Vec::new();
        for row in &loaded {
            let rubric: serde_json::Value = serde_json::from_str(&row.5).unwrap_or(serde_json::json!({}));
            let alternatives = string_array(&rubric, "alternatives");
            let points = string_array(&rubric, "points");
            let options: Vec<McqOption> = row.3.as_deref().and_then(|s| serde_json::from_str(s).ok()).unwrap_or_default();
            let (awarded, method, confidence, explanation, covered, missing, incorrect) =
                if row.12 == "transcription_failed" {
                    (
                        None,
                        "transcription-failed".into(),
                        "review".into(),
                        "The recording could not be transcribed. This answer needs review and is not given an invented mark.".into(),
                        vec![],
                        vec![],
                        vec![],
                    )
                } else if row.1 == "mcq" {
                    let grade = grade_mcq(row.11.as_deref(), &row.4, row.6 as f64);
                    (grade.awarded, grade.method, grade.confidence, grade.explanation, grade.covered, grade.missing, grade.incorrect)
                } else if row.1 == "fib" {
                    let grade = grade_fib(&row.10, &row.4, &alternatives, &confusion, row.6 as f64);
                    (grade.awarded, grade.method, grade.confidence, grade.explanation, grade.covered, grade.missing, grade.incorrect)
                } else {
                    let concepts = points
                        .iter()
                        .map(|point| ConceptRef {
                            kind: "expected_point".into(),
                            label: String::new(),
                            content: point.clone(),
                            aliases: String::new(),
                        })
                        .collect::<Vec<_>>();
                    let model = self.maybe_model(&row.8, &row.10, &points);
                    let grade = grade_descriptive(&row.8, &row.10, &concepts, row.6 as f64, model);
                    (grade.awarded, grade.method, grade.confidence, grade.explanation, grade.covered, grade.missing, grade.incorrect)
                };
            let student_answer = if row.1 == "mcq" {
                let letter = row.11.clone().unwrap_or_default();
                let text = options.iter().find(|o| o.id.eq_ignore_ascii_case(&letter)).map(|o| o.text.clone()).unwrap_or_default();
                if letter.is_empty() { String::new() } else { format!("{letter}. {text}") }
            } else {
                row.10.clone()
            };
            let correct_display = if row.1 == "mcq" {
                let text = options.iter().find(|o| o.id.eq_ignore_ascii_case(&row.4)).map(|o| o.text.clone()).unwrap_or_default();
                format!("{}. {text}", row.4)
            } else if points.is_empty() {
                row.4.clone()
            } else {
                points.join("\n")
            };
            reviews.push(QuestionReview {
                position: row.0,
                question_type: row.1.clone(),
                prompt: row.2.clone(),
                options,
                student_answer,
                correct_answer: correct_display,
                awarded,
                max_marks: row.6,
                explanation,
                source_topic_id: row.7.clone(),
                topic_title: row.9.clone().unwrap_or_default(),
                confidence,
                method,
                covered,
                missing,
                incorrect,
            });
        }
        let obtained: f64 = reviews.iter().filter_map(|q| q.awarded).sum();
        let max_marks: i64 = reviews.iter().map(|q| q.max_marks).sum();
        let percentage = if max_marks == 0 { 0.0 } else { (obtained * 1000.0 / max_marks as f64).round() / 10.0 };
        let mut correct = 0;
        let mut partial = 0;
        let mut incorrect = 0;
        let mut unanswered = 0;
        let mut review = 0;
        for question in &reviews {
            match question.awarded {
                None => review += 1,
                Some(score) if (score - question.max_marks as f64).abs() < 0.001 => correct += 1,
                Some(score) if score > 0.0 => partial += 1,
                Some(_) if question.student_answer.trim().is_empty() => unanswered += 1,
                Some(_) => incorrect += 1,
            }
        }
        let sections = section_scores(&reviews);
        let (started_at, completed_guess): (Option<String>, String) = self.conn.query_row(
            "SELECT started_at, created_at FROM written_exams WHERE id = ?1",
            params![exam_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        let ended = now_ts();
        let time_taken_ms = match started_at {
            Some(start) => timestamp_delta_ms(&start, &ended),
            None => 0,
        };
        let _ = completed_guess;
        let header = self.result_header(exam_id)?;
        Ok(ExamResult {
            exam_id: exam_id.into(),
            student_name: header.0,
            class_name: header.1,
            book_title: header.2,
            chapter_titles: header.3,
            taken_at: ended,
            obtained_marks: (obtained * 10.0).round() / 10.0,
            max_marks,
            percentage,
            time_taken_ms,
            correct_count: correct,
            partial_count: partial,
            incorrect_count: incorrect,
            unanswered_count: unanswered,
            review_count: review,
            sections,
            questions: reviews,
            weighting_note: header.4,
            grading_note: String::new(),
        })
    }

    fn record_written_revision(&mut self, exam_id: &str, result: &ExamResult) -> AppResult<()> {
        let student_id: String = self.conn.query_row(
            "SELECT student_id FROM written_exams WHERE id = ?1",
            params![exam_id],
            |row| row.get(0),
        )?;
        let settings = self.get_settings()?;
        let mut stmt = self.conn.prepare(
            "SELECT q.position, q.rubric_json FROM written_exam_questions q WHERE q.exam_id = ?1",
        )?;
        let rubrics: Vec<(i64, String)> = stmt
            .query_map(params![exam_id], |row| Ok((row.get(0)?, row.get(1)?)))?
            .collect::<Result<Vec<_>, _>>()?;
        drop(stmt);
        let mut buckets: BTreeMap<String, (f64, i64)> = BTreeMap::new();
        for question in &result.questions {
            let Some(awarded) = question.awarded else { continue; };
            if question.max_marks <= 0 { continue; }
            let ratio = awarded / question.max_marks as f64;
            let rubric = rubrics.iter().find(|(pos, _)| *pos == question.position);
            let mut ids = vec![question.source_topic_id.clone()];
            if let Some((_, raw)) = rubric {
                if let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) {
                    ids.extend(string_array(&value, "topicIds"));
                }
            }
            ids.sort();
            ids.dedup();
            for id in ids {
                let entry = buckets.entry(id).or_insert((0.0, 0));
                entry.0 += ratio;
                entry.1 += 1;
            }
        }
        for (topic_id, (sum, count)) in buckets {
            if count == 0 { continue; }
            let percent = sum / count as f64 * 100.0;
            let status = if percent >= settings.well_remembered_percent {
                "well_remembered"
            } else if percent >= settings.developing_percent {
                "developing"
            } else {
                "needs_revision"
            };
            self.set_revision(&student_id, &topic_id, status, Some(percent), "written")?;
        }
        Ok(())
    }

    fn maybe_model(&self, reference: &str, answer: &str, points: &[String]) -> Option<crate::grading::ConceptGrade> {
        let models = self.get_models().ok()?;
        let llama = models.into_iter().find(|m| m.kind == "llama")?;
        crate::speech::try_llama_grade(&llama.binary_path, &llama.model_path, reference, answer, points)
    }

    fn materials_for(&self, student_id: &str, book_id: &str, chapter_ids: &[String]) -> AppResult<Vec<TopicMaterial>> {
        if chapter_ids.is_empty() {
            return Err(AppError::Invalid("Select at least one chapter.".into()));
        }
        self.ensure_profile(student_id)?;
        let owner: String = self.conn.query_row(
            "SELECT c.student_id FROM books b JOIN classes c ON c.id = b.class_id WHERE b.id = ?1 AND b.deleted_at IS NULL",
            params![book_id],
            |row| row.get(0),
        ).map_err(|err| not_found(err, "That book was not found."))?;
        if owner != student_id {
            return Err(AppError::Invalid("That book belongs to another profile.".into()));
        }
        let mut topics = Vec::new();
        for chapter_id in chapter_ids {
            let belongs: Option<String> = self.conn.query_row(
                "SELECT id FROM chapters WHERE id = ?1 AND book_id = ?2 AND deleted_at IS NULL",
                params![chapter_id, book_id],
                |row| row.get(0),
            ).optional()?;
            if belongs.is_none() {
                return Err(AppError::Invalid("Each selected chapter must belong to the chosen book.".into()));
            }
            let mut stmt = self.conn.prepare(
                "SELECT id FROM topics WHERE chapter_id = ?1 AND deleted_at IS NULL ORDER BY sort_order",
            )?;
            let ids: Vec<String> = stmt.query_map(params![chapter_id], |row| row.get(0))?.collect::<Result<Vec<_>, _>>()?;
            for id in ids {
                let material = self.topic_material(&id)?;
                if material.reference_text.trim().is_empty() && material.concepts.is_empty() {
                    continue;
                }
                topics.push(material);
            }
        }
        if topics.is_empty() {
            return Err(AppError::Invalid(
                "The selected chapters have no saved notes yet. Add reference text or key points, then build the paper.".into(),
            ));
        }
        Ok(topics)
    }

    fn book_context(&self, book_id: &str) -> AppResult<(String, String, String)> {
        self.conn.query_row(
            "SELECT c.id, c.name, b.title FROM books b JOIN classes c ON c.id = b.class_id WHERE b.id = ?1",
            params![book_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        ).map_err(|err| not_found(err, "That book was not found."))
    }

    fn chapter_titles(&self, ids: &[String]) -> AppResult<Vec<String>> {
        let mut titles = Vec::new();
        for id in ids {
            let title: String = self.conn.query_row(
                "SELECT title FROM chapters WHERE id = ?1",
                params![id],
                |row| row.get(0),
            ).unwrap_or_else(|_| id.clone());
            titles.push(title);
        }
        Ok(titles)
    }

    fn exam_status(&self, exam_id: &str) -> AppResult<String> {
        self.conn.query_row(
            "SELECT status FROM written_exams WHERE id = ?1",
            params![exam_id],
            |row| row.get(0),
        ).map_err(|err| not_found(err, "That examination was not found."))
    }

    fn question_duration(&self, exam_id: &str, position: i64) -> AppResult<i64> {
        self.conn.query_row(
            "SELECT duration_ms FROM written_exam_questions WHERE exam_id = ?1 AND position = ?2",
            params![exam_id, position],
            |row| row.get(0),
        ).map_err(|err| not_found(err, "That question was not found."))
    }

    fn timer_row(&self, exam_id: &str) -> AppResult<(String, i64, i64, Option<i64>, Option<i64>)> {
        self.conn.query_row(
            "SELECT status, current_index, timer_generation, active_started_wall_ms, active_duration_ms
             FROM written_exams WHERE id = ?1",
            params![exam_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
        ).map_err(|err| not_found(err, "That examination was not found."))
    }

    fn timer_anchor(&self, exam_id: &str) -> AppResult<(Option<i64>, i64, Option<i64>)> {
        let row = self.timer_row(exam_id)?;
        Ok((row.3, row.2, row.4))
    }

    fn result_exists(&self, exam_id: &str) -> AppResult<bool> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM written_exam_results WHERE exam_id = ?1",
            params![exam_id],
            |row| row.get(0),
        )?;
        Ok(count > 0)
    }

    fn result_header(&self, exam_id: &str) -> AppResult<(String, String, String, Vec<String>, String)> {
        let (student, class_name, book, chapters, note): (String, String, String, String, String) = self.conn.query_row(
            "SELECT p.display_name, c.name, b.title, e.chapter_ids_json, e.weighting_note
             FROM written_exams e
             JOIN student_profiles p ON p.id = e.student_id
             JOIN classes c ON c.id = e.class_id
             JOIN books b ON b.id = e.book_id
             WHERE e.id = ?1",
            params![exam_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
        )?;
        let ids: Vec<String> = serde_json::from_str(&chapters).unwrap_or_default();
        let titles = self.chapter_titles(&ids)?;
        Ok((student, class_name, book, titles, note))
    }

    fn exam_view(&self, exam_id: &str, wall_now_ms: i64) -> AppResult<ExamView> {
        let (status, index, generation, started, duration) = self.timer_row(exam_id)?;
        let total: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM written_exam_questions WHERE exam_id = ?1",
            params![exam_id],
            |row| row.get(0),
        )?;
        let (total_marks, weighting, instructions, class_name, book_title): (i64, String, String, String, String) = self.conn.query_row(
            "SELECT e.total_marks, e.weighting_note, e.instructions, c.name, b.title
             FROM written_exams e
             JOIN classes c ON c.id = e.class_id
             JOIN books b ON b.id = e.book_id
             WHERE e.id = ?1",
            params![exam_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
        )?;
        let pending: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM written_exam_answers a
             JOIN written_exam_questions q ON q.id = a.question_id
             WHERE q.exam_id = ?1 AND a.status = 'pending_transcription'",
            params![exam_id],
            |row| row.get(0),
        )?;
        let question = if status == "in_progress" {
            self.question_view(exam_id, index).ok()
        } else {
            None
        };
        let duration_ms = duration.unwrap_or(0).max(0) as u64;
        let remaining_ms = match started {
            Some(start) if status == "in_progress" => {
                let elapsed = wall_now_ms.saturating_sub(start).max(0) as u64;
                duration_ms.saturating_sub(elapsed)
            }
            _ => duration_ms,
        };
        let progress = if total == 0 { 0.0 } else { (index.max(0) as f64 / total as f64).min(1.0) };
        Ok(ExamView {
            exam_id: exam_id.into(),
            status,
            current_index: index.max(0) as usize,
            total_questions: total.max(0) as usize,
            question,
            remaining_ms,
            duration_ms,
            timer_generation: generation,
            started_wall_ms: started,
            progress,
            pending_transcription: pending.max(0) as usize,
            recovery_policy: RECOVERY_POLICY.into(),
            total_marks,
            weighting_note: weighting,
            instructions,
            class_name,
            book_title,
        })
    }

    fn question_view(&self, exam_id: &str, position: i64) -> AppResult<ExamQuestionView> {
        self.conn.query_row(
            "SELECT q.id, q.position, q.question_type, q.prompt, q.options_json, q.max_marks,
                    a.draft_text, a.draft_option, q.locked, q.duration_ms
             FROM written_exam_questions q
             JOIN written_exam_answers a ON a.question_id = q.id
             WHERE q.exam_id = ?1 AND q.position = ?2",
            params![exam_id, position],
            |row| {
                let options: Vec<McqOption> = row.get::<_, Option<String>>(4)?.as_deref().and_then(|s| serde_json::from_str(s).ok()).unwrap_or_default();
                Ok(ExamQuestionView {
                    id: row.get(0)?,
                    position: row.get::<_, i64>(1)? as usize,
                    question_type: row.get(2)?,
                    prompt: row.get(3)?,
                    options,
                    max_marks: row.get(5)?,
                    draft_text: row.get(6)?,
                    draft_option: row.get(7)?,
                    locked: row.get::<_, i64>(8)? == 1,
                    duration_ms: row.get(9)?,
                })
            },
        ).map_err(|err| not_found(err, "That question was not found."))
    }
}

fn duration_for(question_type: &str, settings: &crate::db::Settings) -> i64 {
    let seconds = match question_type {
        "mcq" => settings.mcq_seconds,
        "fib" => settings.fib_seconds,
        "short" => settings.short_seconds,
        "long" => settings.long_seconds,
        _ => 60,
    };
    (seconds as i64) * 1000
}

fn normalize_difficulty(difficulty: &str) -> AppResult<&str> {
    match difficulty {
        "easy" | "standard" | "hard" => Ok(difficulty),
        _ => Err(AppError::Invalid("Choose easy, standard, or hard difficulty.".into())),
    }
}

fn string_array(value: &serde_json::Value, key: &str) -> Vec<String> {
    value.get(key).and_then(|v| v.as_array()).map(|items| {
        items.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect()
    }).unwrap_or_default()
}

fn section_scores(questions: &[QuestionReview]) -> Vec<SectionScore> {
    let groups = [
        ("Fill in the blanks", "fib"),
        ("Multiple choice", "mcq"),
        ("Short questions", "short"),
        ("Long question", "long"),
    ];
    let mut sections = Vec::new();
    for (name, kind) in groups {
        let items: Vec<_> = questions.iter().filter(|q| q.question_type == kind).collect();
        if items.is_empty() {
            continue;
        }
        let mut section = SectionScore {
            name: name.into(),
            awarded: 0.0,
            max_marks: 0,
            correct: 0,
            partial: 0,
            incorrect: 0,
            unanswered: 0,
            review: 0,
        };
        for question in items {
            section.max_marks += question.max_marks;
            match question.awarded {
                None => section.review += 1,
                Some(score) => {
                    section.awarded += score;
                    if (score - question.max_marks as f64).abs() < 0.001 {
                        section.correct += 1;
                    } else if score > 0.0 {
                        section.partial += 1;
                    } else if question.student_answer.trim().is_empty() {
                        section.unanswered += 1;
                    } else {
                        section.incorrect += 1;
                    }
                }
            }
        }
        sections.push(section);
    }
    sections
}

fn timestamp_delta_ms(start: &str, end: &str) -> i64 {
    let start = DateTime::parse_from_rfc3339(start).ok();
    let end = DateTime::parse_from_rfc3339(end).ok();
    match (start, end) {
        (Some(start), Some(end)) => (end.timestamp_millis() - start.timestamp_millis()).max(0),
        _ => 0,
    }
}

pub fn render_result_html(result: &ExamResult) -> String {
    let mut body = String::new();
    body.push_str(&format!(
        "<h1>Examination result</h1><p><strong>{}</strong> · {} · {}</p>",
        escape(&result.student_name),
        escape(&result.class_name),
        escape(&result.book_title)
    ));
    body.push_str(&format!(
        "<p>Chapters: {}</p><p>Date: {}</p><p>Score: {} / {} ({}%)</p><p>Time: {}</p>",
        escape(&result.chapter_titles.join(", ")),
        escape(&result.taken_at),
        result.obtained_marks,
        result.max_marks,
        result.percentage,
        format_ms(result.time_taken_ms)
    ));
    body.push_str(&format!(
        "<p>Correct: {} · Partial: {} · Incorrect: {} · Unanswered: {} · Review: {}</p>",
        result.correct_count, result.partial_count, result.incorrect_count, result.unanswered_count, result.review_count
    ));
    body.push_str(&format!("<p>{}</p><p>{}</p>", escape(&result.weighting_note), escape(&result.grading_note)));
    for section in &result.sections {
        body.push_str(&format!(
            "<h2>{}</h2><p>{} / {}</p>",
            escape(&section.name), section.awarded, section.max_marks
        ));
    }
    for question in &result.questions {
        body.push_str(&format!(
            "<article><h3>Question {} · {} · {} / {}</h3><p>{}</p><p><strong>Your answer</strong></p><p dir=\"auto\">{}</p><p><strong>Expected</strong></p><p dir=\"auto\">{}</p><p>{}</p><p>Topic: {}</p></article>",
            question.position + 1,
            escape(&question.question_type),
            question.awarded.map(|v| v.to_string()).unwrap_or_else(|| "review".into()),
            question.max_marks,
            escape(&question.prompt),
            escape(&question.student_answer),
            escape(&question.correct_answer),
            escape(&question.explanation),
            escape(&question.topic_title)
        ));
    }
    format!(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Result</title>
        <style>body{{font-family:Georgia,serif;margin:2rem;line-height:1.45;color:#1c2430}} article{{border-top:1px solid #ddd;padding:1rem 0}}</style>
        </head><body>{body}<p>Print this page and choose Save as PDF. Urdu text uses the fonts installed on this computer.</p></body></html>"
    )
}

fn escape(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

fn format_ms(ms: i64) -> String {
    let total = ms.max(0) / 1000;
    format!("{}m {:02}s", total / 60, total % 60)
}

