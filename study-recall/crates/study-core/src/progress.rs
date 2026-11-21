use rusqlite::params;
use serde::{Deserialize, Serialize};

use crate::db::Database;
use crate::error::AppResult;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GroupScore {
    pub id: String,
    pub label: String,
    pub parent_label: String,
    pub average_percent: Option<f64>,
    pub attempts: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MissedConcept {
    pub concept: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScorePoint {
    pub id: String,
    pub label: String,
    pub percentage: f64,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RevisionTopic {
    pub topic_id: String,
    pub title: String,
    pub class_name: String,
    pub book_title: String,
    pub chapter_title: String,
    pub status: String,
    pub last_score: Option<f64>,
    pub last_source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgressDashboard {
    pub tests_completed: i64,
    pub oral_sessions: i64,
    pub written_exams: i64,
    pub average_oral: Option<f64>,
    pub average_written: Option<f64>,
    pub by_class: Vec<GroupScore>,
    pub by_book: Vec<GroupScore>,
    pub by_chapter: Vec<GroupScore>,
    pub by_topic: Vec<GroupScore>,
    pub missed_concepts: Vec<MissedConcept>,
    pub needs_revision: i64,
    pub developing: i64,
    pub well_remembered: i64,
    pub untested: i64,
    pub revision_completed: i64,
    pub recent_written: Vec<ScorePoint>,
    pub recent_oral: Vec<ScorePoint>,
    pub well_remembered_percent: f64,
    pub developing_percent: f64,
}

impl Database {
    pub fn progress(&self, student_id: &str) -> AppResult<ProgressDashboard> {
        self.ensure_profile(student_id)?;
        let settings = self.get_settings()?;
        let oral_sessions: i64 = self.count(
            "SELECT COUNT(*) FROM oral_test_sessions WHERE student_id = ?1 AND status = 'completed'",
            student_id,
        )?;
        let written_exams: i64 = self.count(
            "SELECT COUNT(*) FROM written_exams WHERE student_id = ?1 AND status = 'completed'",
            student_id,
        )?;
        let average_oral = self.optional_real(
            "SELECT AVG(s.overall) FROM oral_test_scores s
             JOIN oral_test_responses r ON r.id = s.response_id
             JOIN oral_test_sessions o ON o.id = r.session_id
             WHERE o.student_id = ?1 AND r.skipped = 0 AND s.confidence != 'review'",
            student_id,
        )?;
        let average_written = self.optional_real(
            "SELECT AVG(r.percentage) FROM written_exam_results r
             JOIN written_exams e ON e.id = r.exam_id
             WHERE e.student_id = ?1",
            student_id,
        )?;
        let by_class = self.group_scores(
            "SELECT c.id, c.name, '', AVG(score), COUNT(*) FROM (
                SELECT o.class_id AS gid, s.overall AS score
                FROM oral_test_scores s
                JOIN oral_test_responses r ON r.id = s.response_id
                JOIN oral_test_sessions o ON o.id = r.session_id
                WHERE o.student_id = ?1 AND r.skipped = 0 AND o.class_id IS NOT NULL
                UNION ALL
                SELECT e.class_id, r.percentage
                FROM written_exam_results r JOIN written_exams e ON e.id = r.exam_id
                WHERE e.student_id = ?1
             ) scores
             JOIN classes c ON c.id = scores.gid
             GROUP BY c.id
             ORDER BY c.name",
            student_id,
        )?;
        let by_book = self.group_scores(
            "SELECT b.id, b.title, c.name, AVG(qscore), COUNT(*) FROM (
                SELECT t.id AS topic_id, s.overall AS qscore
                FROM oral_test_scores s
                JOIN oral_test_responses r ON r.id = s.response_id
                JOIN oral_test_sessions o ON o.id = r.session_id
                JOIN topics t ON t.id = r.topic_id
                WHERE o.student_id = ?1 AND r.skipped = 0
                UNION ALL
                SELECT q.source_topic_id, CASE WHEN q.max_marks = 0 THEN 0 ELSE a.awarded_marks * 100.0 / q.max_marks END
                FROM written_exam_answers a
                JOIN written_exam_questions q ON q.id = a.question_id
                JOIN written_exams e ON e.id = q.exam_id
                WHERE e.student_id = ?1 AND a.awarded_marks IS NOT NULL
             ) x
             JOIN topics t ON t.id = x.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             GROUP BY b.id
             ORDER BY b.title",
            student_id,
        )?;
        let by_chapter = self.group_scores(
            "SELECT ch.id, ch.title, b.title, AVG(qscore), COUNT(*) FROM (
                SELECT t.id AS topic_id, s.overall AS qscore
                FROM oral_test_scores s
                JOIN oral_test_responses r ON r.id = s.response_id
                JOIN oral_test_sessions o ON o.id = r.session_id
                JOIN topics t ON t.id = r.topic_id
                WHERE o.student_id = ?1 AND r.skipped = 0
                UNION ALL
                SELECT q.source_topic_id, CASE WHEN q.max_marks = 0 THEN 0 ELSE a.awarded_marks * 100.0 / q.max_marks END
                FROM written_exam_answers a
                JOIN written_exam_questions q ON q.id = a.question_id
                JOIN written_exams e ON e.id = q.exam_id
                WHERE e.student_id = ?1 AND a.awarded_marks IS NOT NULL
             ) x
             JOIN topics t ON t.id = x.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             GROUP BY ch.id
             ORDER BY ch.title",
            student_id,
        )?;
        let by_topic = self.group_scores(
            "SELECT t.id, t.title, ch.title, AVG(qscore), COUNT(*) FROM (
                SELECT t.id AS topic_id, s.overall AS qscore
                FROM oral_test_scores s
                JOIN oral_test_responses r ON r.id = s.response_id
                JOIN oral_test_sessions o ON o.id = r.session_id
                JOIN topics t ON t.id = r.topic_id
                WHERE o.student_id = ?1 AND r.skipped = 0
                UNION ALL
                SELECT q.source_topic_id, CASE WHEN q.max_marks = 0 THEN 0 ELSE a.awarded_marks * 100.0 / q.max_marks END
                FROM written_exam_answers a
                JOIN written_exam_questions q ON q.id = a.question_id
                JOIN written_exams e ON e.id = q.exam_id
                WHERE e.student_id = ?1 AND a.awarded_marks IS NOT NULL
             ) x
             JOIN topics t ON t.id = x.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             GROUP BY t.id
             ORDER BY AVG(qscore) ASC",
            student_id,
        )?;
        let missed = self.missed_concepts(student_id)?;
        let needs_revision = self.count(
            "SELECT COUNT(*) FROM topic_revision_status r
             JOIN topics t ON t.id = r.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND r.status = 'needs_revision' AND t.deleted_at IS NULL",
            student_id,
        )?;
        let developing = self.count(
            "SELECT COUNT(*) FROM topic_revision_status r
             JOIN topics t ON t.id = r.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND r.status = 'developing' AND t.deleted_at IS NULL",
            student_id,
        )?;
        let well_remembered = self.count(
            "SELECT COUNT(*) FROM topic_revision_status r
             JOIN topics t ON t.id = r.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND r.status = 'well_remembered' AND t.deleted_at IS NULL",
            student_id,
        )?;
        let topics_total = self.count(
            "SELECT COUNT(*) FROM topics t
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND t.deleted_at IS NULL AND ch.deleted_at IS NULL
               AND b.deleted_at IS NULL AND c.deleted_at IS NULL",
            student_id,
        )?;
        let revision_completed = self.count(
            "SELECT COUNT(*) FROM revision_events
             WHERE student_id = ?1 AND previous_status = 'needs_revision'
               AND new_status IN ('developing', 'well_remembered')",
            student_id,
        )?;
        Ok(ProgressDashboard {
            tests_completed: oral_sessions + written_exams,
            oral_sessions,
            written_exams,
            average_oral: round_opt(average_oral),
            average_written: round_opt(average_written),
            by_class,
            by_book,
            by_chapter,
            by_topic,
            missed_concepts: missed,
            needs_revision,
            developing,
            well_remembered,
            untested: (topics_total - needs_revision - developing - well_remembered).max(0),
            revision_completed,
            recent_written: self.recent_written(student_id)?,
            recent_oral: self.recent_oral(student_id)?,
            well_remembered_percent: settings.well_remembered_percent,
            developing_percent: settings.developing_percent,
        })
    }

    pub fn revision_topics(&self, student_id: &str, class_id: Option<&str>) -> AppResult<Vec<RevisionTopic>> {
        self.ensure_profile(student_id)?;
        let mut stmt = self.conn.prepare(
            "SELECT t.id, t.title, c.name, b.title, ch.title, r.status, r.last_score, IFNULL(r.last_source, '')
             FROM topic_revision_status r
             JOIN topics t ON t.id = r.topic_id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND r.status = 'needs_revision'
               AND (?2 = '' OR c.id = ?2)
               AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL AND c.deleted_at IS NULL
             ORDER BY r.updated_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id, class_id.unwrap_or("")], |row| {
            Ok(RevisionTopic {
                topic_id: row.get(0)?,
                title: row.get(1)?,
                class_name: row.get(2)?,
                book_title: row.get(3)?,
                chapter_title: row.get(4)?,
                status: row.get(5)?,
                last_score: row.get(6)?,
                last_source: row.get(7)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn count(&self, sql: &str, student_id: &str) -> AppResult<i64> {
        Ok(self.conn.query_row(sql, params![student_id], |row| row.get(0))?)
    }

    fn optional_real(&self, sql: &str, student_id: &str) -> AppResult<Option<f64>> {
        Ok(self.conn.query_row(sql, params![student_id], |row| row.get(0))?)
    }

    fn group_scores(&self, sql: &str, student_id: &str) -> AppResult<Vec<GroupScore>> {
        let mut stmt = self.conn.prepare(sql)?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(GroupScore {
                id: row.get(0)?,
                label: row.get(1)?,
                parent_label: row.get(2)?,
                average_percent: row.get::<_, Option<f64>>(3)?.map(|v| (v * 10.0).round() / 10.0),
                attempts: row.get(4)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn missed_concepts(&self, student_id: &str) -> AppResult<Vec<MissedConcept>> {
        let mut counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::new();
        let mut stmt = self.conn.prepare(
            "SELECT s.feedback_json FROM oral_test_scores s
             JOIN oral_test_responses r ON r.id = s.response_id
             JOIN oral_test_sessions o ON o.id = r.session_id
             WHERE o.student_id = ?1
             ORDER BY s.created_at DESC LIMIT 200",
        )?;
        let rows = stmt.query_map(params![student_id], |row| row.get::<_, String>(0))?;
        for row in rows {
            add_missing(&mut counts, &row?);
        }
        let mut stmt = self.conn.prepare(
            "SELECT a.grading_json FROM written_exam_answers a
             JOIN written_exam_questions q ON q.id = a.question_id
             JOIN written_exams e ON e.id = q.exam_id
             WHERE e.student_id = ?1 AND a.grading_json IS NOT NULL
             ORDER BY e.created_at DESC LIMIT 200",
        )?;
        let rows = stmt.query_map(params![student_id], |row| row.get::<_, String>(0))?;
        for row in rows {
            add_missing(&mut counts, &row?);
        }
        let mut list: Vec<_> = counts
            .into_iter()
            .map(|(concept, count)| MissedConcept { concept, count })
            .collect();
        list.sort_by(|a, b| b.count.cmp(&a.count).then(a.concept.cmp(&b.concept)));
        list.truncate(12);
        Ok(list)
    }

    fn recent_written(&self, student_id: &str) -> AppResult<Vec<ScorePoint>> {
        let mut stmt = self.conn.prepare(
            "SELECT e.id, r.created_at, r.percentage
             FROM written_exam_results r JOIN written_exams e ON e.id = r.exam_id
             WHERE e.student_id = ?1
             ORDER BY r.created_at DESC LIMIT 8",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(ScorePoint {
                id: row.get(0)?,
                label: row.get(1)?,
                percentage: row.get(2)?,
                kind: "written".into(),
            })
        })?;
        let mut points = rows.collect::<Result<Vec<_>, _>>()?;
        points.reverse();
        Ok(points)
    }

    fn recent_oral(&self, student_id: &str) -> AppResult<Vec<ScorePoint>> {
        let mut stmt = self.conn.prepare(
            "SELECT o.id, IFNULL(o.completed_at, o.created_at), AVG(s.overall)
             FROM oral_test_sessions o
             JOIN oral_test_responses r ON r.session_id = o.id AND r.skipped = 0
             JOIN oral_test_scores s ON s.response_id = r.id
             WHERE o.student_id = ?1 AND o.status = 'completed'
             GROUP BY o.id
             ORDER BY o.created_at DESC LIMIT 8",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(ScorePoint {
                id: row.get(0)?,
                label: row.get(1)?,
                percentage: row.get::<_, f64>(2)?,
                kind: "oral".into(),
            })
        })?;
        let mut points = rows.collect::<Result<Vec<_>, _>>()?;
        points.reverse();
        Ok(points)
    }
}

fn round_opt(value: Option<f64>) -> Option<f64> {
    value.map(|v| (v * 10.0).round() / 10.0)
}

fn add_missing(counts: &mut std::collections::BTreeMap<String, i64>, raw: &str) {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) else { return; };
    let Some(items) = value.get("missing").and_then(|v| v.as_array()) else { return; };
    for item in items {
        if let Some(text) = item.as_str() {
            let text = text.trim();
            if text.is_empty() {
                continue;
            }
            *counts.entry(text.to_string()).or_insert(0) += 1;
        }
    }
}
