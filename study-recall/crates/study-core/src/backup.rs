use std::fs;
use std::path::Path;

use rusqlite::{types::ToSql, Connection};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::db::{new_id, now_ts, Database};
use crate::error::{AppError, AppResult};

const TABLES: &[&str] = &[
    "student_profiles",
    "classes",
    "books",
    "chapters",
    "topics",
    "topic_notes",
    "topic_key_concepts",
    "oral_test_sessions",
    "oral_test_responses",
    "oral_test_scores",
    "written_exams",
    "written_exam_questions",
    "written_exam_answers",
    "written_exam_results",
    "topic_revision_status",
    "revision_events",
    "application_settings",
    "model_configuration",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackupEntry {
    pub id: String,
    pub path: String,
    pub action: String,
    pub status: String,
    pub message: String,
    pub created_at: String,
}

#[derive(Debug)]
enum SqlValue {
    Null,
    Integer(i64),
    Real(f64),
    Text(String),
}

impl ToSql for SqlValue {
    fn to_sql(&self) -> rusqlite::Result<rusqlite::types::ToSqlOutput<'_>> {
        match self {
            SqlValue::Null => Ok(rusqlite::types::ToSqlOutput::from(rusqlite::types::Null)),
            SqlValue::Integer(v) => Ok(rusqlite::types::ToSqlOutput::from(*v)),
            SqlValue::Real(v) => Ok(rusqlite::types::ToSqlOutput::from(*v)),
            SqlValue::Text(v) => Ok(rusqlite::types::ToSqlOutput::from(v.as_str())),
        }
    }
}

impl Database {
    pub fn backup_to(&self, dest: &Path) -> AppResult<()> {
        if let Some(parent) = dest.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent).map_err(|err| AppError::Backup(err.to_string()))?;
            }
        }
        if dest.exists() {
            let message = "Choose a new file name. An existing backup was not overwritten.";
            self.log_backup(&dest.display().to_string(), "backup", "error", message);
            return Err(AppError::Backup(message.into()));
        }
        let mut dst = Connection::open(dest).map_err(|err| AppError::Backup(err.to_string()))?;
        let result = (|| {
            {
                let backup = rusqlite::backup::Backup::new(&self.conn, &mut dst)?;
                backup.step(-1)?;
            }
            let check: String = dst.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
            if check != "ok" {
                return Err(AppError::Backup(format!(
                    "The new backup failed its integrity check: {check}"
                )));
            }
            Ok(())
        })();
        if let Err(err) = result {
            drop(dst);
            let _ = fs::remove_file(dest);
            self.log_backup(&dest.display().to_string(), "backup", "error", &err.to_string());
            return Err(err);
        }
        self.log_backup(&dest.display().to_string(), "backup", "ok", "Backup completed.");
        Ok(())
    }

    pub fn restore_from(&mut self, src: &Path) -> AppResult<()> {
        if !src.exists() {
            let message = "The backup file was not found.";
            self.log_backup(&src.display().to_string(), "restore", "error", message);
            return Err(AppError::Backup(message.into()));
        }
        let src_conn = Connection::open(src).map_err(|err| AppError::Backup(err.to_string()))?;
        src_conn.pragma_update(None, "foreign_keys", "ON")?;
        let check: String = src_conn
            .query_row("PRAGMA integrity_check", [], |row| row.get(0))
            .map_err(|err| AppError::Backup(err.to_string()))?;
        if check != "ok" {
            let message = format!("The backup failed its integrity check: {check}");
            self.log_backup(&src.display().to_string(), "restore", "error", &message);
            return Err(AppError::Backup(message));
        }
        let version: i64 = src_conn
            .query_row(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
                [],
                |row| row.get(0),
            )
            .map_err(|_| AppError::Backup("This file is not a Study Recall backup.".into()))?;
        if version < 1 {
            return Err(AppError::Backup("This file is not a Study Recall backup.".into()));
        }
        if self.path == Path::new(":memory:") {
            let mut new_conn = Connection::open_in_memory()?;
            {
                let backup = rusqlite::backup::Backup::new(&src_conn, &mut new_conn)?;
                backup.step(-1)?;
            }
            new_conn.pragma_update(None, "foreign_keys", "ON")?;
            self.conn = new_conn;
            self.log_backup(&src.display().to_string(), "restore", "ok", "In-memory database restored.");
            return Ok(());
        }
        let temp = self.path.with_extension("restore-tmp");
        let backup_copy = self.path.with_extension("db.bak");
        if temp.exists() {
            let _ = fs::remove_file(&temp);
        }
        {
            let mut temp_conn = Connection::open(&temp).map_err(|err| AppError::Backup(err.to_string()))?;
            {
                let backup = rusqlite::backup::Backup::new(&src_conn, &mut temp_conn)?;
                backup.step(-1)?;
            }
            let check: String = temp_conn.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
            if check != "ok" {
                drop(temp_conn);
                let _ = fs::remove_file(&temp);
                return Err(AppError::Backup(format!(
                    "The restored copy failed its integrity check: {check}"
                )));
            }
        }
        self.conn = Connection::open_in_memory()?;
        if backup_copy.exists() {
            let _ = fs::remove_file(&backup_copy);
        }
        if let Err(err) = fs::rename(&self.path, &backup_copy) {
            self.reopen_file()?;
            return Err(AppError::Backup(format!("Could not move the current database aside: {err}")));
        }
        if let Err(err) = fs::rename(&temp, &self.path) {
            let _ = fs::rename(&backup_copy, &self.path);
            self.reopen_file()?;
            return Err(AppError::Backup(format!("Could not put the backup in place: {err}")));
        }
        let _ = fs::remove_file(&backup_copy);
        self.reopen_file()?;
        self.log_backup(&src.display().to_string(), "restore", "ok", "Database restored.");
        Ok(())
    }

    pub fn export_json(&self) -> AppResult<String> {
        let mut root = Map::new();
        root.insert("format".into(), Value::String("study-recall-export".into()));
        root.insert("version".into(), Value::from(1));
        root.insert("exportedAt".into(), Value::String(now_ts()));
        for table in TABLES {
            root.insert((*table).into(), Value::Array(self.dump_table(table)?));
        }
        serde_json::to_string_pretty(&Value::Object(root))
            .map_err(|err| AppError::Backup(err.to_string()))
    }

    pub fn import_json(&mut self, raw: &str) -> AppResult<usize> {
        let value: Value = serde_json::from_str(raw)
            .map_err(|_| AppError::Backup("The import file is not valid JSON.".into()))?;
        let obj = value
            .as_object()
            .ok_or_else(|| AppError::Backup("The import file is not a Study Recall export.".into()))?;
        if obj.get("format").and_then(|v| v.as_str()) != Some("study-recall-export") {
            return Err(AppError::Backup("The import file is not a Study Recall export.".into()));
        }
        let mut id_map: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::new();
        for table in TABLES {
            if let Some(rows) = obj.get(*table).and_then(|v| v.as_array()) {
                for row in rows {
                    if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
                        id_map.insert(id.to_string(), new_id());
                    }
                }
            }
        }
        let tx = self.conn.transaction()?;
        let mut inserted = 0usize;
        for table in TABLES {
            let Some(rows) = obj.get(*table).and_then(|v| v.as_array()) else { continue; };
            for row in rows {
                let Some(map) = row.as_object() else { continue; };
                let rewritten = rewrite_row(map, &id_map);
                if *table == "application_settings" {
                    upsert_setting(&tx, &rewritten)?;
                } else if *table == "model_configuration" {
                    update_model_row(&tx, &rewritten)?;
                } else {
                    insert_dynamic(&tx, table, &rewritten)?;
                }
                inserted += 1;
            }
        }
        tx.commit()?;
        self.log_backup("json-import", "import", "ok", &format!("Imported {inserted} rows."));
        Ok(inserted)
    }

    pub fn backup_history(&self) -> AppResult<Vec<BackupEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, path, action, status, message, created_at FROM backup_log ORDER BY created_at DESC LIMIT 30",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(BackupEntry {
                id: row.get(0)?,
                path: row.get(1)?,
                action: row.get(2)?,
                status: row.get(3)?,
                message: row.get(4)?,
                created_at: row.get(5)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    fn dump_table(&self, table: &str) -> AppResult<Vec<Value>> {
        if !TABLES.contains(&table) {
            return Err(AppError::Backup("Unknown table.".into()));
        }
        let mut stmt = self.conn.prepare(&format!("SELECT * FROM {table}"))?;
        let names: Vec<String> = stmt.column_names().iter().map(|s| (*s).to_string()).collect();
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let mut obj = Map::new();
            for (index, name) in names.iter().enumerate() {
                obj.insert(name.clone(), sqlite_value(row, index)?);
            }
            out.push(Value::Object(obj));
        }
        Ok(out)
    }

    fn reopen_file(&mut self) -> AppResult<()> {
        self.conn = Connection::open(&self.path)?;
        self.conn.busy_timeout(std::time::Duration::from_secs(5))?;
        self.conn.pragma_update(None, "foreign_keys", "ON")?;
        self.conn.pragma_update(None, "journal_mode", "WAL")?;
        Ok(())
    }
}

fn sqlite_value(row: &rusqlite::Row<'_>, index: usize) -> AppResult<Value> {
    let value: rusqlite::types::Value = row.get(index)?;
    Ok(match value {
        rusqlite::types::Value::Null => Value::Null,
        rusqlite::types::Value::Integer(v) => Value::from(v),
        rusqlite::types::Value::Real(v) => serde_json::Number::from_f64(v).map(Value::Number).unwrap_or(Value::Null),
        rusqlite::types::Value::Text(v) => Value::String(v),
        rusqlite::types::Value::Blob(_) => Value::Null,
    })
}

fn rewrite_row(row: &Map<String, Value>, id_map: &std::collections::BTreeMap<String, String>) -> Map<String, Value> {
    let mut out = Map::new();
    for (key, value) in row {
        out.insert(key.clone(), rewrite_value(key, value, id_map));
    }
    out
}

fn rewrite_value(key: &str, value: &Value, id_map: &std::collections::BTreeMap<String, String>) -> Value {
    match value {
        Value::String(text) => {
            if let Some(mapped) = id_map.get(text) {
                if key == "id" || key.ends_with("_id") || key == "active_student_id" {
                    return Value::String(mapped.clone());
                }
            }
            if key.ends_with("_json") || key == "feedback_json" || key == "grading_json" || key == "draft_concepts_json" {
                if let Ok(parsed) = serde_json::from_str::<Value>(text) {
                    let replaced = replace_ids(&parsed, id_map);
                    return Value::String(replaced.to_string());
                }
            }
            Value::String(text.clone())
        }
        other => other.clone(),
    }
}

fn replace_ids(value: &Value, id_map: &std::collections::BTreeMap<String, String>) -> Value {
    match value {
        Value::String(text) => {
            if let Some(mapped) = id_map.get(text) {
                Value::String(mapped.clone())
            } else {
                Value::String(text.clone())
            }
        }
        Value::Array(items) => Value::Array(items.iter().map(|item| replace_ids(item, id_map)).collect()),
        Value::Object(map) => {
            let mut out = Map::new();
            for (key, item) in map {
                out.insert(key.clone(), replace_ids(item, id_map));
            }
            Value::Object(out)
        }
        other => other.clone(),
    }
}

fn insert_dynamic(conn: &Connection, table: &str, row: &Map<String, Value>) -> AppResult<()> {
    if !TABLES.contains(&table) {
        return Err(AppError::Backup("Unknown table.".into()));
    }
    let columns: Vec<&String> = row.keys().collect();
    if columns.is_empty() {
        return Ok(());
    }
    let placeholders = (1..=columns.len()).map(|n| format!("?{n}")).collect::<Vec<_>>().join(", ");
    let names = columns.iter().map(|c| c.as_str()).collect::<Vec<_>>().join(", ");
    let sql = format!("INSERT INTO {table} ({names}) VALUES ({placeholders})");
    let values: Vec<SqlValue> = row.values().map(json_to_sql).collect();
    let params: Vec<&dyn ToSql> = values.iter().map(|v| v as &dyn ToSql).collect();
    conn.execute(&sql, params.as_slice())?;
    Ok(())
}

fn json_to_sql(value: &Value) -> SqlValue {
    match value {
        Value::Null => SqlValue::Null,
        Value::Bool(v) => SqlValue::Integer(if *v { 1 } else { 0 }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                SqlValue::Integer(i)
            } else if let Some(f) = n.as_f64() {
                SqlValue::Real(f)
            } else {
                SqlValue::Text(n.to_string())
            }
        }
        Value::String(s) => SqlValue::Text(s.clone()),
        other => SqlValue::Text(other.to_string()),
    }
}

fn upsert_setting(conn: &Connection, row: &Map<String, Value>) -> AppResult<()> {
    let key = row.get("key").and_then(|v| v.as_str()).unwrap_or("");
    let value = row.get("value").and_then(|v| v.as_str()).unwrap_or("");
    let updated = row.get("updated_at").and_then(|v| v.as_str()).unwrap_or("");
    conn.execute(
        "INSERT INTO application_settings (key, value, updated_at) VALUES (?1, ?2, ?3)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        rusqlite::params![key, value, updated],
    )?;
    Ok(())
}

fn update_model_row(conn: &Connection, row: &Map<String, Value>) -> AppResult<()> {
    let kind = row.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    let binary = row.get("binary_path").and_then(|v| v.as_str()).unwrap_or("");
    let model = row.get("model_path").and_then(|v| v.as_str()).unwrap_or("");
    let message = row.get("status_message").and_then(|v| v.as_str()).unwrap_or("");
    let available = row.get("available").and_then(|v| v.as_i64()).unwrap_or(0);
    conn.execute(
        "UPDATE model_configuration
         SET binary_path = ?1, model_path = ?2, available = ?3, status_message = ?4, updated_at = ?5
         WHERE kind = ?6",
        rusqlite::params![binary, model, available, message, now_ts(), kind],
    )?;
    Ok(())
}
