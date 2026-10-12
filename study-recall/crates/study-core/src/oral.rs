use rand::rngs::StdRng;
use rand::SeedableRng;
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

use crate::db::{new_id, not_found, now_ts, Database};
use crate::error::{AppError, AppResult};
use crate::grading::{grade_recall, oral_percent, ConceptGrade};
use crate::questions::{shuffle, TopicMaterial};
use crate::speech::try_llama_grade;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OralPrompt {
    pub session_id: String,
    pub position: usize,
    pub total: usize,
    pub topic_id: String,
    pub topic_title: String,
    pub class_name: String,
    pub book_title: String,
    pub chapter_title: String,
    pub language: String,
    pub text_direction: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OralTopicResult {
    pub topic_id: String,
    pub title: String,
    pub skipped: bool,
    pub transcript: String,
    pub reference_text: String,
    pub essential_coverage: Option<f64>,
    pub factual_correctness: Option<f64>,
    pub supporting_detail: Option<f64>,
    pub overall: Option<f64>,
    pub method: String,
    pub confidence: String,
    pub covered: Vec<String>,
    pub missing: Vec<String>,
    pub incorrect: Vec<String>,
    pub revision: String,
    pub category: String,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OralSummary {
    pub session_id: String,
    pub status: String,
    pub attempted: usize,
    pub skipped: usize,
    pub average_percent: Option<f64>,
    pub successful: usize,
    pub partial: usize,
    pub needs_revision: usize,
    pub well_remembered_percent: f64,
    pub developing_percent: f64,
    pub topics: Vec<OralTopicResult>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OralStep {
    pub finished: bool,
    pub result: OralTopicResult,
    pub summary: Option<OralSummary>,
}

impl Database {
    pub fn start_oral(
        &mut self,
        student_id: &str,
        chapter_id: &str,
        seed: Option<u64>,
    ) -> AppResult<OralPrompt> {
        self.ensure_profile(student_id)?;
        let owner = self.student_of_chapter(chapter_id)?;
        if owner != student_id {
            return Err(AppError::Invalid("That chapter belongs to another profile.".into()));
        }
        let topics = self.topics_with_notes(chapter_id)?;
        if topics.is_empty() {
            return Err(AppError::Invalid(
                "This chapter has no topics with saved reference notes. Add notes, then start the oral test.".into(),
            ));
        }
        let (class_id, book_id) = self.chapter_parents(chapter_id)?;
        self.insert_oral(student_id, Some(class_id), Some(book_id), Some(chapter_id.to_string()), "chapter", topics, seed)
    }

    pub fn start_revision_oral(
        &mut self,
        student_id: &str,
        class_id: Option<String>,
        seed: Option<u64>,
    ) -> AppResult<OralPrompt> {
        self.ensure_profile(student_id)?;
        let topics = self.weak_topics(student_id, class_id.as_deref())?;
        if topics.is_empty() {
            return Err(AppError::Invalid(
                "No topics are currently marked as needing revision. Complete an oral or written test first.".into(),
            ));
        }
        self.insert_oral(student_id, class_id, None, None, "revision", topics, seed)
    }

    pub fn get_oral_prompt(&self, session_id: &str) -> AppResult<Option<OralPrompt>> {
        let (status, index, order) = self.oral_cursor(session_id)?;
        if status != "in_progress" || index >= order.len() {
            return Ok(None);
        }
        Ok(Some(self.prompt_for(session_id, &order[index], index, order.len())?))
    }

    pub fn submit_oral(&mut self, session_id: &str, transcript: &str) -> AppResult<OralStep> {
        self.score_current(session_id, transcript, false)
    }

    pub fn skip_oral(&mut self, session_id: &str) -> AppResult<OralStep> {
        self.score_current(session_id, "", true)
    }

    pub fn oral_summary(&self, session_id: &str) -> AppResult<OralSummary> {
        self.summary_for(session_id)
    }

    fn insert_oral(
        &mut self,
        student_id: &str,
        class_id: Option<String>,
        book_id: Option<String>,
        chapter_id: Option<String>,
        kind: &str,
        topics: Vec<String>,
        seed: Option<u64>,
    ) -> AppResult<OralPrompt> {
        let mut order = topics;
        let mut rng = match seed {
            Some(seed) => StdRng::seed_from_u64(seed),
            None => StdRng::from_entropy(),
        };
        shuffle(&mut order, &mut rng);
        if order.len() != order.iter().collect::<std::collections::BTreeSet<_>>().len() {
            return Err(AppError::Invalid("The topic list contained a repeated topic.".into()));
        }
        let id = new_id();
        let order_json = serde_json::to_string(&order).map_err(|err| AppError::Invalid(err.to_string()))?;
        self.conn.execute(
            "INSERT INTO oral_test_sessions
             (id, student_id, class_id, book_id, chapter_id, session_kind, status, topic_order_json, current_index, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'in_progress', ?7, 0, ?8)",
            params![id, student_id, class_id, book_id, chapter_id, kind, order_json, now_ts()],
        )?;
        self.prompt_for(&id, &order[0], 0, order.len())
    }

    fn score_current(&mut self, session_id: &str, transcript: &str, skipped: bool) -> AppResult<OralStep> {
        let (status, index, order) = self.oral_cursor(session_id)?;
        if status != "in_progress" || index >= order.len() {
            return Err(AppError::Conflict("This oral test is already complete.".into()));
        }
        let topic_id = order[index].clone();
        let student_id: String = self.conn.query_row(
            "SELECT student_id FROM oral_test_sessions WHERE id = ?1",
            params![session_id],
            |row| row.get(0),
        )?;
        let material = self.topic_material(&topic_id)?;
        let response_id = new_id();
        let ts = now_ts();
        let settings = self.get_settings()?;
        let (grade, overall) = if skipped {
            (None, None)
        } else {
            let mut grade = grade_recall(&material.reference_text, transcript, &material.concepts);
            if let Some(model) = self.maybe_llama(&material.reference_text, transcript, &grade) {
                grade = crate::grading::apply_model_grade(grade, model);
            }
            let overall = oral_percent(&grade);
            (Some(grade), overall)
        };
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO oral_test_responses (id, session_id, topic_id, transcript, skipped, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![response_id, session_id, topic_id, transcript.trim(), if skipped { 1 } else { 0 }, ts],
        )?;
        if let Some(grade) = &grade {
            let feedback = serde_json::json!({
                "covered": grade.covered,
                "missing": grade.missing,
                "incorrect": grade.incorrect,
                "reasons": grade.reasons,
                "revision": revision_text(&material.title, grade),
            });
            tx.execute(
                "INSERT INTO oral_test_scores
                 (id, response_id, essential_coverage, factual_correctness, supporting_detail, overall, method, confidence, feedback_json, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    new_id(),
                    response_id,
                    grade.essential * 100.0,
                    grade.factual * 100.0,
                    grade.supporting * 100.0,
                    overall.unwrap_or(0.0),
                    grade.method,
                    grade.confidence,
                    feedback.to_string(),
                    ts
                ],
            )?;
        }
        let next = index + 1;
        if next >= order.len() {
            tx.execute(
                "UPDATE oral_test_sessions SET current_index = ?1, status = 'completed', completed_at = ?2 WHERE id = ?3",
                params![next as i64, ts, session_id],
            )?;
        } else {
            tx.execute(
                "UPDATE oral_test_sessions SET current_index = ?1 WHERE id = ?2",
                params![next as i64, session_id],
            )?;
        }
        tx.commit()?;
        let category = category_for(skipped, overall, settings.well_remembered_percent, settings.developing_percent);
        let status_name = if skipped || category == "needs_revision" {
            "needs_revision"
        } else if category == "successful" {
            "well_remembered"
        } else {
            "developing"
        };
        self.set_revision(
            &student_id,
            &topic_id,
            status_name,
            if skipped { None } else { overall },
            "oral",
        )?;
        let result = self.topic_result(&response_id, &material.title, skipped, grade.as_ref(), overall, &category)?;
        let finished = next >= order.len();
        let summary = if finished { Some(self.summary_for(session_id)?) } else { None };
        Ok(OralStep { finished, result, summary })
    }

    fn maybe_llama(&self, reference: &str, answer: &str, rubric: &ConceptGrade) -> Option<crate::grading::ConceptGrade> {
        if rubric.confidence == "review" {
            return None;
        }
        let models = self.get_models().ok()?;
        let llama = models.into_iter().find(|m| m.kind == "llama")?;
        let points: Vec<String> = rubric.covered.iter().chain(rubric.missing.iter()).cloned().collect();
        try_llama_grade(&llama.binary_path, &llama.model_path, reference, answer, &points)
    }

    fn summary_for(&self, session_id: &str) -> AppResult<OralSummary> {
        let status: String = self.conn.query_row(
            "SELECT status FROM oral_test_sessions WHERE id = ?1",
            params![session_id],
            |row| row.get(0),
        ).map_err(|err| not_found(err, "That oral test was not found."))?;
        let settings = self.get_settings()?;
        let mut stmt = self.conn.prepare(
            "SELECT r.id, r.topic_id, t.title, r.transcript, r.skipped, n.reference_text,
                    s.essential_coverage, s.factual_correctness, s.supporting_detail, s.overall,
                    s.method, s.confidence, s.feedback_json
             FROM oral_test_responses r
             JOIN topics t ON t.id = r.topic_id
             LEFT JOIN topic_notes n ON n.topic_id = t.id
             LEFT JOIN oral_test_scores s ON s.response_id = r.id
             WHERE r.session_id = ?1
             ORDER BY r.created_at",
        )?;
        let rows = stmt.query_map(params![session_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, i64>(4)? == 1,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<f64>>(6)?,
                row.get::<_, Option<f64>>(7)?,
                row.get::<_, Option<f64>>(8)?,
                row.get::<_, Option<f64>>(9)?,
                row.get::<_, Option<String>>(10)?,
                row.get::<_, Option<String>>(11)?,
                row.get::<_, Option<String>>(12)?,
            ))
        })?;
        let mut topics = Vec::new();
        for row in rows {
            let row = row?;
            let feedback: serde_json::Value = row.12.as_deref().and_then(|s| serde_json::from_str(s).ok()).unwrap_or(serde_json::json!({}));
            let category = category_for(row.4, row.9, settings.well_remembered_percent, settings.developing_percent);
            topics.push(OralTopicResult {
                topic_id: row.1,
                title: row.2.clone(),
                skipped: row.4,
                transcript: row.3,
                reference_text: row.5.unwrap_or_default(),
                essential_coverage: row.6,
                factual_correctness: row.7,
                supporting_detail: row.8,
                overall: row.9,
                method: row.10.unwrap_or_else(|| if row.4 { "skipped".into() } else { String::new() }),
                confidence: row.11.unwrap_or_default(),
                covered: string_list(&feedback, "covered"),
                missing: string_list(&feedback, "missing"),
                incorrect: string_list(&feedback, "incorrect"),
                revision: feedback.get("revision").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                category,
                reasons: string_list(&feedback, "reasons"),
            });
        }
        let attempted: Vec<_> = topics.iter().filter(|t| !t.skipped).collect();
        let skipped = topics.iter().filter(|t| t.skipped).count();
        let successful = attempted.iter().filter(|t| t.category == "successful").count();
        let partial = attempted.iter().filter(|t| t.category == "partial").count();
        let needs_revision = attempted.iter().filter(|t| t.category == "needs_revision").count();
        let average = if attempted.is_empty() {
            None
        } else {
            let sum: f64 = attempted.iter().filter_map(|t| t.overall).sum();
            Some((sum / attempted.len() as f64 * 10.0).round() / 10.0)
        };
        Ok(OralSummary {
            session_id: session_id.into(),
            status,
            attempted: attempted.len(),
            skipped,
            average_percent: average,
            successful,
            partial,
            needs_revision,
            well_remembered_percent: settings.well_remembered_percent,
            developing_percent: settings.developing_percent,
            topics,
        })
    }

    fn topic_result(
        &self,
        _response_id: &str,
        title: &str,
        skipped: bool,
        grade: Option<&ConceptGrade>,
        overall: Option<f64>,
        category: &str,
    ) -> AppResult<OralTopicResult> {
        let (topic_id, transcript, reference) = self.conn.query_row(
            "SELECT r.topic_id, r.transcript, IFNULL(n.reference_text, '')
             FROM oral_test_responses r
             LEFT JOIN topic_notes n ON n.topic_id = r.topic_id
             WHERE r.id = ?1",
            params![_response_id],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?)),
        )?;
        let grade = grade.cloned();
        Ok(OralTopicResult {
            topic_id,
            title: title.into(),
            skipped,
            transcript,
            reference_text: reference,
            essential_coverage: grade.as_ref().map(|g| g.essential * 100.0),
            factual_correctness: grade.as_ref().map(|g| g.factual * 100.0),
            supporting_detail: grade.as_ref().map(|g| g.supporting * 100.0),
            overall,
            method: grade.as_ref().map(|g| g.method.clone()).unwrap_or_else(|| "skipped".into()),
            confidence: grade.as_ref().map(|g| g.confidence.clone()).unwrap_or_default(),
            covered: grade.as_ref().map(|g| g.covered.clone()).unwrap_or_default(),
            missing: grade.as_ref().map(|g| g.missing.clone()).unwrap_or_default(),
            incorrect: grade.as_ref().map(|g| g.incorrect.clone()).unwrap_or_default(),
            revision: grade.as_ref().map(|g| revision_text(title, g)).unwrap_or_else(|| format!("Review the topic: {title}.")),
            category: category.into(),
            reasons: grade.as_ref().map(|g| g.reasons.clone()).unwrap_or_default(),
        })
    }

    fn topics_with_notes(&self, chapter_id: &str) -> AppResult<Vec<String>> {
        let mut stmt = self.conn.prepare(
            "SELECT t.id FROM topics t
             JOIN topic_notes n ON n.topic_id = t.id
             WHERE t.chapter_id = ?1 AND t.deleted_at IS NULL AND length(trim(n.reference_text)) > 0
             ORDER BY t.sort_order",
        )?;
        let rows = stmt.query_map(params![chapter_id], |row| row.get(0))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn weak_topics(&self, student_id: &str, class_id: Option<&str>) -> AppResult<Vec<String>> {
        let mut stmt = self.conn.prepare(
            "SELECT t.id FROM topics t
             JOIN topic_revision_status r ON r.topic_id = t.id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             JOIN topic_notes n ON n.topic_id = t.id
             WHERE r.student_id = ?1 AND r.status = 'needs_revision'
               AND c.student_id = ?1 AND (?2 = '' OR c.id = ?2)
               AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL AND c.deleted_at IS NULL
               AND length(trim(n.reference_text)) > 0
             ORDER BY t.title",
        )?;
        let class_id = class_id.unwrap_or("");
        let rows = stmt.query_map(params![student_id, class_id], |row| row.get(0))?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn chapter_parents(&self, chapter_id: &str) -> AppResult<(String, String)> {
        self.conn
            .query_row(
                "SELECT c.id, b.id FROM chapters ch
                 JOIN books b ON b.id = ch.book_id
                 JOIN classes c ON c.id = b.class_id
                 WHERE ch.id = ?1",
                params![chapter_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(|err| not_found(err, "That chapter was not found."))
    }

    fn oral_cursor(&self, session_id: &str) -> AppResult<(String, usize, Vec<String>)> {
        let (status, index, order_json): (String, i64, String) = self
            .conn
            .query_row(
                "SELECT status, current_index, topic_order_json FROM oral_test_sessions WHERE id = ?1",
                params![session_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .map_err(|err| not_found(err, "That oral test was not found."))?;
        let order: Vec<String> = serde_json::from_str(&order_json).unwrap_or_default();
        Ok((status, index.max(0) as usize, order))
    }

    fn prompt_for(&self, session_id: &str, topic_id: &str, position: usize, total: usize) -> AppResult<OralPrompt> {
        let row = self.conn.query_row(
            "SELECT t.title, t.language, n.text_direction, c.name, b.title, ch.title
             FROM topics t
             JOIN topic_notes n ON n.topic_id = t.id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE t.id = ?1",
            params![topic_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                ))
            },
        ).optional()?;
        let (title, language, direction, class_name, book_title, chapter_title) = row.unwrap_or_else(|| {
            ("Topic".into(), "en".into(), "ltr".into(), String::new(), String::new(), String::new())
        });
        Ok(OralPrompt {
            session_id: session_id.into(),
            position,
            total,
            topic_id: topic_id.into(),
            topic_title: title,
            class_name,
            book_title,
            chapter_title,
            language,
            text_direction: direction,
        })
    }

    pub(crate) fn topic_material(&self, topic_id: &str) -> AppResult<TopicMaterial> {
        let (title, reference, language): (String, String, String) = self.conn.query_row(
            "SELECT t.title, IFNULL(n.reference_text, ''), t.language
             FROM topics t LEFT JOIN topic_notes n ON n.topic_id = t.id
             WHERE t.id = ?1",
            params![topic_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        ).map_err(|err| not_found(err, "That topic was not found."))?;
        Ok(TopicMaterial {
            id: topic_id.into(),
            title,
            reference_text: reference,
            language,
            concepts: self.concepts_for(topic_id)?,
        })
    }
}

fn category_for(skipped: bool, overall: Option<f64>, well: f64, developing: f64) -> String {
    if skipped {
        return "skipped".into();
    }
    match overall {
        Some(score) if score >= well => "successful".into(),
        Some(score) if score >= developing => "partial".into(),
        _ => "needs_revision".into(),
    }
}

fn revision_text(title: &str, grade: &ConceptGrade) -> String {
    if grade.missing.is_empty() && grade.incorrect.is_empty() {
        format!("Review {title} only if you want to strengthen the explanation.")
    } else {
        let missing = if grade.missing.is_empty() {
            String::new()
        } else {
            format!(" Look again at: {}.", grade.missing.join("; "))
        };
        format!("Review the topic: {title}.{missing}")
    }
}

fn string_list(value: &serde_json::Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(|v| v.as_array())
        .map(|items| items.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default()
}
