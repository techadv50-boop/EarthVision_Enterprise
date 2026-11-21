use std::path::{Path, PathBuf};
use std::time::Duration;

use chrono::{SecondsFormat, Utc};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::speech::{assess_llama, assess_whisper};

pub const RECOVERY_POLICY: &str = "While an examination question is on screen, the countdown uses a monotonic clock so changing the computer clock does not reset or skip the timer. The application saves the active question, the draft answer, and the start time. If the application closes, reopening it settles only the question that was active: elapsed time is subtracted using the saved start time. If that question's time has already run out, the saved draft is kept, an empty draft is marked unanswered, and the next question starts with its full time. Later questions are not consumed while the application is closed. Transcription that is still running does not block the next question. Final marks are calculated after pending transcriptions finish or are recorded as errors that need review.";

const SCHEMA_V1: &str = r#"
CREATE TABLE student_profiles (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'en' CHECK (preferred_language IN ('en', 'ur')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE classes (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE books (
    id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'ur')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE topics (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'ur')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE topic_notes (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL UNIQUE REFERENCES topics(id) ON DELETE CASCADE,
    reference_text TEXT NOT NULL DEFAULT '',
    draft_text TEXT NOT NULL DEFAULT '',
    draft_concepts_json TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'en',
    text_direction TEXT NOT NULL DEFAULT 'ltr' CHECK (text_direction IN ('ltr', 'rtl')),
    updated_at TEXT NOT NULL
);
CREATE TABLE topic_key_concepts (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('definition', 'fact', 'keyword', 'formula', 'example', 'expected_point')),
    label TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE oral_test_sessions (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    class_id TEXT,
    book_id TEXT,
    chapter_id TEXT,
    session_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    topic_order_json TEXT NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE oral_test_responses (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES oral_test_sessions(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    transcript TEXT NOT NULL DEFAULT '',
    skipped INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE oral_test_scores (
    id TEXT PRIMARY KEY,
    response_id TEXT NOT NULL UNIQUE REFERENCES oral_test_responses(id) ON DELETE CASCADE,
    essential_coverage REAL NOT NULL,
    factual_correctness REAL NOT NULL,
    supporting_detail REAL NOT NULL,
    overall REAL NOT NULL,
    method TEXT NOT NULL,
    confidence TEXT NOT NULL,
    feedback_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE written_exams (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    class_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    chapter_ids_json TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    paper_size TEXT NOT NULL,
    status TEXT NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    timer_generation INTEGER NOT NULL DEFAULT 0,
    active_started_wall_ms INTEGER,
    active_duration_ms INTEGER,
    seed INTEGER NOT NULL DEFAULT 0,
    total_marks INTEGER NOT NULL,
    weighting_note TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    recovery_policy TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE TABLE written_exam_questions (
    id TEXT PRIMARY KEY,
    exam_id TEXT NOT NULL REFERENCES written_exams(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    question_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    options_json TEXT,
    correct_answer TEXT NOT NULL,
    rubric_json TEXT NOT NULL,
    max_marks INTEGER NOT NULL,
    source_topic_id TEXT NOT NULL,
    source_passage TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    UNIQUE (exam_id, position)
);
CREATE TABLE written_exam_answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL UNIQUE REFERENCES written_exam_questions(id) ON DELETE CASCADE,
    draft_text TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL DEFAULT '',
    selected_option TEXT,
    draft_option TEXT,
    status TEXT NOT NULL DEFAULT 'unanswered',
    timed_out INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT,
    awarded_marks REAL,
    grading_method TEXT,
    grading_confidence TEXT,
    grading_json TEXT
);
CREATE TABLE written_exam_results (
    id TEXT PRIMARY KEY,
    exam_id TEXT NOT NULL UNIQUE REFERENCES written_exams(id) ON DELETE CASCADE,
    obtained_marks REAL NOT NULL,
    graded_max_marks REAL NOT NULL,
    paper_max_marks INTEGER NOT NULL,
    percentage REAL NOT NULL,
    percentage_if_review_is_zero REAL NOT NULL,
    correct_count INTEGER NOT NULL,
    incorrect_count INTEGER NOT NULL,
    partial_count INTEGER NOT NULL,
    unanswered_count INTEGER NOT NULL,
    review_count INTEGER NOT NULL,
    section_json TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    time_taken_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE topic_revision_status (
    topic_id TEXT PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL,
    status TEXT NOT NULL,
    last_score REAL,
    last_source TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE revision_events (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    score REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE application_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE model_configuration (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL UNIQUE,
    binary_path TEXT NOT NULL DEFAULT '',
    model_path TEXT NOT NULL DEFAULT '',
    extra_args TEXT NOT NULL DEFAULT '',
    available INTEGER NOT NULL DEFAULT 0,
    status_message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE backup_log (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_classes_student ON classes(student_id, deleted_at, sort_order);
CREATE INDEX idx_books_class ON books(class_id, deleted_at, sort_order);
CREATE INDEX idx_chapters_book ON chapters(book_id, deleted_at, sort_order);
CREATE INDEX idx_topics_chapter ON topics(chapter_id, deleted_at, sort_order);
CREATE INDEX idx_topics_title ON topics(title);
CREATE INDEX idx_concepts_topic ON topic_key_concepts(topic_id, sort_order);
CREATE INDEX idx_oral_student ON oral_test_sessions(student_id, status);
CREATE INDEX idx_oral_response_session ON oral_test_responses(session_id);
CREATE INDEX idx_exam_student ON written_exams(student_id, status);
CREATE INDEX idx_exam_questions_exam ON written_exam_questions(exam_id, position);
CREATE INDEX idx_revision_student ON topic_revision_status(student_id, status);
CREATE INDEX idx_revision_events_student ON revision_events(student_id, created_at);
"#;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Profile {
    pub id: String,
    pub display_name: String,
    pub preferred_language: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub theme: String,
    pub mcq_seconds: u64,
    pub fib_seconds: u64,
    pub short_seconds: u64,
    pub long_seconds: u64,
    pub well_remembered_percent: f64,
    pub developing_percent: f64,
    pub active_student_id: String,
    pub retain_audio: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsUpdate {
    pub theme: Option<String>,
    pub mcq_seconds: Option<u64>,
    pub fib_seconds: Option<u64>,
    pub short_seconds: Option<u64>,
    pub long_seconds: Option<u64>,
    pub well_remembered_percent: Option<f64>,
    pub developing_percent: Option<f64>,
    pub active_student_id: Option<String>,
    pub retain_audio: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelInfo {
    pub kind: String,
    pub binary_path: String,
    pub model_path: String,
    pub available: bool,
    pub status_message: String,
}

pub struct Database {
    pub(crate) conn: Connection,
    pub(crate) path: PathBuf,
}

impl Database {
    pub fn open(path: impl AsRef<Path>) -> AppResult<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).map_err(|err| {
                    AppError::Database(format!("Could not create the data folder: {err}"))
                })?;
            }
        }
        let conn = Connection::open(&path)?;
        let mut db = Database { conn, path };
        db.configure()?;
        db.migrate()?;
        Ok(db)
    }

    pub fn open_in_memory() -> AppResult<Self> {
        let conn = Connection::open_in_memory()?;
        let mut db = Database {
            conn,
            path: PathBuf::from(":memory:"),
        };
        db.configure()?;
        db.migrate()?;
        Ok(db)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn integrity_check(&self) -> AppResult<String> {
        let result: String = self
            .conn
            .query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
        Ok(result)
    }

    fn configure(&self) -> AppResult<()> {
        self.conn.busy_timeout(Duration::from_secs(5))?;
        self.conn.pragma_update(None, "foreign_keys", "ON")?;
        if self.path != PathBuf::from(":memory:") {
            self.conn.pragma_update(None, "journal_mode", "WAL")?;
        }
        Ok(())
    }

    fn migrate(&mut self) -> AppResult<()> {
        self.conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );",
        )?;
        let current: i64 = self.conn.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
            [],
            |row| row.get(0),
        )?;
        if current < 1 {
            let tx = self.conn.transaction()?;
            tx.execute_batch(SCHEMA_V1)?;
            let ts = now_ts();
            seed_defaults(&tx, &ts)?;
            tx.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?1)",
                params![ts],
            )?;
            tx.pragma_update(None, "user_version", 1i64)?;
            tx.commit()?;
        }
        Ok(())
    }

    pub fn create_profile(&mut self, name: &str, language: &str) -> AppResult<Profile> {
        let name = require_label(name, "Enter the student name.", 80)?;
        let language = crate::textutil::normalize_language(language)
            .map_err(AppError::Invalid)?;
        if language == "auto" {
            return Err(AppError::Invalid("Choose English or Urdu.".into()));
        }
        let id = new_id();
        let ts = now_ts();
        self.conn.execute(
            "INSERT INTO student_profiles (id, display_name, preferred_language, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?4)",
            params![id, name, language, ts],
        )?;
        let _ = self.set_setting_raw("active_student_id", &id);
        self.get_profile(&id)
    }

    pub fn update_profile(&mut self, id: &str, name: &str, language: &str) -> AppResult<Profile> {
        let name = require_label(name, "Enter the student name.", 80)?;
        let language = crate::textutil::normalize_language(language).map_err(AppError::Invalid)?;
        if language == "auto" {
            return Err(AppError::Invalid("Choose English or Urdu.".into()));
        }
        let changed = self.conn.execute(
            "UPDATE student_profiles SET display_name = ?1, preferred_language = ?2, updated_at = ?3 WHERE id = ?4",
            params![name, language, now_ts(), id],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That student profile was not found.".into()));
        }
        self.get_profile(id)
    }

    pub fn list_profiles(&self) -> AppResult<Vec<Profile>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, display_name, preferred_language, created_at, updated_at
             FROM student_profiles ORDER BY created_at",
        )?;
        let rows = stmt.query_map([], map_profile)?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn get_profile(&self, id: &str) -> AppResult<Profile> {
        self.conn
            .query_row(
                "SELECT id, display_name, preferred_language, created_at, updated_at
                 FROM student_profiles WHERE id = ?1",
                params![id],
                map_profile,
            )
            .map_err(|err| match err {
                rusqlite::Error::QueryReturnedNoRows => {
                    AppError::NotFound("That student profile was not found.".into())
                }
                other => other.into(),
            })
    }

    pub fn get_settings(&self) -> AppResult<Settings> {
        Ok(Settings {
            theme: self.setting_or("theme", "light"),
            mcq_seconds: self.setting_or("mcq_seconds", "45").parse().unwrap_or(45),
            fib_seconds: self.setting_or("fib_seconds", "60").parse().unwrap_or(60),
            short_seconds: self.setting_or("short_seconds", "240").parse().unwrap_or(240),
            long_seconds: self.setting_or("long_seconds", "600").parse().unwrap_or(600),
            well_remembered_percent: self
                .setting_or("well_remembered_percent", "80")
                .parse()
                .unwrap_or(80.0),
            developing_percent: self
                .setting_or("developing_percent", "50")
                .parse()
                .unwrap_or(50.0),
            active_student_id: self.setting_or("active_student_id", ""),
            retain_audio: self.setting_or("retain_audio", "false") == "true",
        })
    }

    pub fn update_settings(&mut self, update: SettingsUpdate) -> AppResult<Settings> {
        let mut next = self.get_settings()?;
        if let Some(theme) = update.theme {
            if theme != "light" && theme != "dark" {
                return Err(AppError::Invalid("Choose the light or dark theme.".into()));
            }
            next.theme = theme;
        }
        if let Some(value) = update.mcq_seconds {
            next.mcq_seconds = bounded_seconds(value, 10, 600, "multiple-choice")?;
        }
        if let Some(value) = update.fib_seconds {
            next.fib_seconds = bounded_seconds(value, 10, 600, "fill-in-the-blank")?;
        }
        if let Some(value) = update.short_seconds {
            next.short_seconds = bounded_seconds(value, 30, 1800, "short-answer")?;
        }
        if let Some(value) = update.long_seconds {
            next.long_seconds = bounded_seconds(value, 60, 3600, "long-answer")?;
        }
        if let Some(value) = update.well_remembered_percent {
            next.well_remembered_percent = value;
        }
        if let Some(value) = update.developing_percent {
            next.developing_percent = value;
        }
        if !(0.0..=100.0).contains(&next.well_remembered_percent)
            || !(0.0..=100.0).contains(&next.developing_percent)
            || next.developing_percent >= next.well_remembered_percent
        {
            return Err(AppError::Invalid(
                "The developing threshold must be lower than the well-remembered threshold, and both must be between 0 and 100.".into(),
            ));
        }
        if let Some(value) = update.active_student_id {
            if !value.is_empty() {
                self.get_profile(&value)?;
            }
            next.active_student_id = value;
        }
        if let Some(value) = update.retain_audio {
            next.retain_audio = value;
        }
        self.set_setting_raw("theme", &next.theme)?;
        self.set_setting_raw("mcq_seconds", &next.mcq_seconds.to_string())?;
        self.set_setting_raw("fib_seconds", &next.fib_seconds.to_string())?;
        self.set_setting_raw("short_seconds", &next.short_seconds.to_string())?;
        self.set_setting_raw("long_seconds", &next.long_seconds.to_string())?;
        self.set_setting_raw(
            "well_remembered_percent",
            &next.well_remembered_percent.to_string(),
        )?;
        self.set_setting_raw("developing_percent", &next.developing_percent.to_string())?;
        self.set_setting_raw("active_student_id", &next.active_student_id)?;
        self.set_setting_raw("retain_audio", if next.retain_audio { "true" } else { "false" })?;
        Ok(next)
    }

    pub fn get_models(&self) -> AppResult<Vec<ModelInfo>> {
        let mut stmt = self.conn.prepare(
            "SELECT kind, binary_path, model_path, available, status_message
             FROM model_configuration ORDER BY kind",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(ModelInfo {
                kind: row.get(0)?,
                binary_path: row.get(1)?,
                model_path: row.get(2)?,
                available: row.get::<_, i64>(3)? == 1,
                status_message: row.get(4)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn update_model(
        &mut self,
        kind: &str,
        binary_path: &str,
        model_path: &str,
    ) -> AppResult<ModelInfo> {
        if kind != "whisper" && kind != "llama" {
            return Err(AppError::Invalid("Choose the Whisper or the grading model.".into()));
        }
        let (available, message) = if kind == "whisper" {
            assess_whisper(binary_path, model_path)
        } else {
            assess_llama(binary_path, model_path)
        };
        let changed = self.conn.execute(
            "UPDATE model_configuration
             SET binary_path = ?1, model_path = ?2, available = ?3, status_message = ?4, updated_at = ?5
             WHERE kind = ?6",
            params![
                binary_path.trim(),
                model_path.trim(),
                if available { 1 } else { 0 },
                message,
                now_ts(),
                kind
            ],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That model configuration was not found.".into()));
        }
        self.get_models()?
            .into_iter()
            .find(|m| m.kind == kind)
            .ok_or_else(|| AppError::NotFound("That model configuration was not found.".into()))
    }

    pub fn refresh_models(&mut self) -> AppResult<Vec<ModelInfo>> {
        let current = self.get_models()?;
        for model in current {
            self.update_model(&model.kind, &model.binary_path, &model.model_path)?;
        }
        self.get_models()
    }

    pub(crate) fn setting_or(&self, key: &str, default: &str) -> String {
        self.conn
            .query_row(
                "SELECT value FROM application_settings WHERE key = ?1",
                params![key],
                |row| row.get(0),
            )
            .unwrap_or_else(|_| default.to_string())
    }

    pub(crate) fn set_setting_raw(&mut self, key: &str, value: &str) -> AppResult<()> {
        self.conn.execute(
            "INSERT INTO application_settings (key, value, updated_at) VALUES (?1, ?2, ?3)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            params![key, value, now_ts()],
        )?;
        Ok(())
    }

    pub(crate) fn log_backup(&self, path: &str, action: &str, status: &str, message: &str) {
        let _ = self.conn.execute(
            "INSERT INTO backup_log (id, path, action, status, message, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![new_id(), path, action, status, message, now_ts()],
        );
    }
}

fn seed_defaults(conn: &Connection, ts: &str) -> AppResult<()> {
    let settings = [
        ("theme", "light"),
        ("mcq_seconds", "45"),
        ("fib_seconds", "60"),
        ("short_seconds", "240"),
        ("long_seconds", "600"),
        ("well_remembered_percent", "80"),
        ("developing_percent", "50"),
        ("active_student_id", ""),
        ("retain_audio", "false"),
    ];
    for (key, value) in settings {
        conn.execute(
            "INSERT INTO application_settings (key, value, updated_at) VALUES (?1, ?2, ?3)",
            params![key, value, ts],
        )?;
    }
    conn.execute(
        "INSERT INTO model_configuration
         (id, kind, binary_path, model_path, extra_args, available, status_message, updated_at)
         VALUES (?1, 'whisper', '', '', '', 0, ?2, ?3)",
        params![
            new_id(),
            "Speech recognition is included with Study Recall. If this message remains, the installed speech files were not found and you can type or paste text.",
            ts
        ],
    )?;
    conn.execute(
        "INSERT INTO model_configuration
         (id, kind, binary_path, model_path, extra_args, available, status_message, updated_at)
         VALUES (?1, 'llama', '', '', '', 0, ?2, ?3)",
        params![
            new_id(),
            "A local language model is not configured. Descriptive scores use the approximate concept rubric, which is labeled in every result.",
            ts
        ],
    )?;
    Ok(())
}

fn map_profile(row: &rusqlite::Row<'_>) -> rusqlite::Result<Profile> {
    Ok(Profile {
        id: row.get(0)?,
        display_name: row.get(1)?,
        preferred_language: row.get(2)?,
        created_at: row.get(3)?,
        updated_at: row.get(4)?,
    })
}

pub fn now_ts() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

pub fn new_id() -> String {
    Uuid::new_v4().to_string()
}

pub fn require_label(value: &str, message: &str, max: usize) -> AppResult<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err(AppError::Invalid(message.into()));
    }
    if trimmed.chars().count() > max {
        return Err(AppError::Invalid(format!(
            "Use {max} characters or fewer."
        )));
    }
    Ok(trimmed.to_string())
}

fn bounded_seconds(value: u64, min: u64, max: u64, label: &str) -> AppResult<u64> {
    if value < min || value > max {
        return Err(AppError::Invalid(format!(
            "The {label} timer must be between {min} and {max} seconds."
        )));
    }
    Ok(value)
}

pub fn not_found(err: rusqlite::Error, message: &str) -> AppError {
    match err {
        rusqlite::Error::QueryReturnedNoRows => AppError::NotFound(message.into()),
        other => other.into(),
    }
}
