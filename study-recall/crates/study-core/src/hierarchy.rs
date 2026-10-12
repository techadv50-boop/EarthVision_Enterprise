use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

use crate::db::{new_id, not_found, now_ts, require_label, Database};
use crate::error::{AppError, AppResult};
use crate::grading::ConceptRef;
use crate::textutil::{direction_for_language, like_pattern, normalize_language};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClassSummary {
    pub id: String,
    pub name: String,
    pub description: String,
    pub sort_order: i64,
    pub archived: bool,
    pub book_count: i64,
    pub topic_count: i64,
    pub studied_topic_count: i64,
    pub tested_topic_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BookSummary {
    pub id: String,
    pub class_id: String,
    pub title: String,
    pub language: String,
    pub sort_order: i64,
    pub archived: bool,
    pub chapter_count: i64,
    pub topic_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChapterSummary {
    pub id: String,
    pub book_id: String,
    pub title: String,
    pub sort_order: i64,
    pub archived: bool,
    pub topic_count: i64,
    pub studied_topic_count: i64,
    pub tested_topic_count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicSummary {
    pub id: String,
    pub chapter_id: String,
    pub title: String,
    pub language: String,
    pub sort_order: i64,
    pub archived: bool,
    pub has_reference: bool,
    pub revision_status: String,
    pub last_score: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ClassNode {
    #[serde(flatten)]
    pub class: ClassSummary,
    pub books: Vec<BookNode>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BookNode {
    #[serde(flatten)]
    pub book: BookSummary,
    pub chapters: Vec<ChapterNode>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChapterNode {
    #[serde(flatten)]
    pub chapter: ChapterSummary,
    pub topics: Vec<TopicSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicHit {
    pub topic_id: String,
    pub title: String,
    pub language: String,
    pub class_id: String,
    pub class_name: String,
    pub book_id: String,
    pub book_title: String,
    pub chapter_id: String,
    pub chapter_title: String,
    pub has_reference: bool,
    pub revision_status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TrashItem {
    pub kind: String,
    pub id: String,
    pub name: String,
    pub deleted_at: String,
    pub parent_label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicDetail {
    pub id: String,
    pub title: String,
    pub language: String,
    pub text_direction: String,
    pub class_id: String,
    pub class_name: String,
    pub book_id: String,
    pub book_title: String,
    pub chapter_id: String,
    pub chapter_title: String,
    pub reference_text: String,
    pub draft_text: String,
    pub has_draft: bool,
    pub concepts: Vec<ConceptRef>,
    pub draft_concepts: Vec<ConceptRef>,
    pub revision_status: String,
    pub last_score: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicDraftInput {
    pub title: String,
    pub language: String,
    pub draft_text: String,
    pub concepts: Vec<ConceptRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicSaveInput {
    pub title: String,
    pub language: String,
    pub reference_text: String,
    pub concepts: Vec<ConceptRef>,
}

impl Database {
    pub fn list_classes(&self, student_id: &str, include_archived: bool) -> AppResult<Vec<ClassSummary>> {
        self.ensure_profile(student_id)?;
        let mut stmt = self.conn.prepare(
            "SELECT c.id, c.name, c.description, c.sort_order, c.archived_at IS NOT NULL,
                (SELECT COUNT(*) FROM books b WHERE b.class_id = c.id AND b.deleted_at IS NULL),
                (SELECT COUNT(*) FROM topics t
                    JOIN chapters ch ON ch.id = t.chapter_id
                    JOIN books b ON b.id = ch.book_id
                    WHERE b.class_id = c.id AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL),
                (SELECT COUNT(*) FROM topics t
                    JOIN chapters ch ON ch.id = t.chapter_id
                    JOIN books b ON b.id = ch.book_id
                    JOIN topic_notes n ON n.topic_id = t.id
                    WHERE b.class_id = c.id AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL
                      AND length(trim(n.reference_text)) > 0),
                (SELECT COUNT(*) FROM topics t
                    JOIN chapters ch ON ch.id = t.chapter_id
                    JOIN books b ON b.id = ch.book_id
                    JOIN topic_revision_status r ON r.topic_id = t.id
                    WHERE b.class_id = c.id AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL)
             FROM classes c
             WHERE c.student_id = ?1 AND c.deleted_at IS NULL AND (?2 = 1 OR c.archived_at IS NULL)
             ORDER BY c.sort_order, c.created_at",
        )?;
        let rows = stmt.query_map(params![student_id, include_archived as i64], |row| {
            Ok(ClassSummary {
                id: row.get(0)?,
                name: row.get(1)?,
                description: row.get(2)?,
                sort_order: row.get(3)?,
                archived: row.get(4)?,
                book_count: row.get(5)?,
                topic_count: row.get(6)?,
                studied_topic_count: row.get(7)?,
                tested_topic_count: row.get(8)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn create_class(&mut self, student_id: &str, name: &str, description: &str) -> AppResult<ClassSummary> {
        self.ensure_profile(student_id)?;
        let name = require_label(name, "Enter a class name.", 120)?;
        let description = description.trim();
        if description.chars().count() > 500 {
            return Err(AppError::Invalid("Use 500 characters or fewer for the description.".into()));
        }
        let id = new_id();
        let ts = now_ts();
        let sort = self.next_sort("classes", "student_id", student_id)?;
        self.conn.execute(
            "INSERT INTO classes (id, student_id, name, description, sort_order, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
            params![id, student_id, name, description, sort, ts],
        )?;
        self.class_summary(&id)
    }

    pub fn update_class(&mut self, id: &str, name: &str, description: &str) -> AppResult<ClassSummary> {
        let name = require_label(name, "Enter a class name.", 120)?;
        let changed = self.conn.execute(
            "UPDATE classes SET name = ?1, description = ?2, updated_at = ?3 WHERE id = ?4 AND deleted_at IS NULL",
            params![name, description.trim(), now_ts(), id],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That class was not found.".into()));
        }
        self.class_summary(id)
    }

    pub fn reorder_classes(&mut self, student_id: &str, ordered_ids: &[String]) -> AppResult<()> {
        self.reorder_children("classes", "student_id", student_id, ordered_ids)
    }

    pub fn set_class_archived(&mut self, id: &str, archived: bool) -> AppResult<ClassSummary> {
        self.set_archived("classes", id, archived)?;
        self.class_summary(id)
    }

    pub fn soft_delete_class(&mut self, id: &str) -> AppResult<()> {
        self.soft_delete("classes", id, "That class was not found.")
    }

    pub fn restore_class(&mut self, id: &str) -> AppResult<ClassSummary> {
        self.restore("classes", id, "That class is not in Recently deleted.")?;
        self.class_summary(id)
    }

    pub fn purge_class(&mut self, id: &str, confirmation: &str) -> AppResult<()> {
        self.purge("classes", id, confirmation)
    }

    pub fn list_books(&self, class_id: &str, include_archived: bool) -> AppResult<Vec<BookSummary>> {
        self.ensure_live("classes", class_id, "That class was not found.")?;
        let mut stmt = self.conn.prepare(
            "SELECT b.id, b.class_id, b.title, b.language, b.sort_order, b.archived_at IS NOT NULL,
                (SELECT COUNT(*) FROM chapters ch WHERE ch.book_id = b.id AND ch.deleted_at IS NULL),
                (SELECT COUNT(*) FROM topics t JOIN chapters ch ON ch.id = t.chapter_id
                    WHERE ch.book_id = b.id AND t.deleted_at IS NULL AND ch.deleted_at IS NULL)
             FROM books b
             WHERE b.class_id = ?1 AND b.deleted_at IS NULL AND (?2 = 1 OR b.archived_at IS NULL)
             ORDER BY b.sort_order, b.created_at",
        )?;
        let rows = stmt.query_map(params![class_id, include_archived as i64], map_book)?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn create_book(&mut self, class_id: &str, title: &str, language: &str) -> AppResult<BookSummary> {
        self.ensure_live("classes", class_id, "That class was not found.")?;
        let title = require_label(title, "Enter a book or subject name.", 160)?;
        let language = study_language(language)?;
        let id = new_id();
        let sort = self.next_sort("books", "class_id", class_id)?;
        self.conn.execute(
            "INSERT INTO books (id, class_id, title, language, sort_order, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
            params![id, class_id, title, language, sort, now_ts()],
        )?;
        self.book_summary(&id)
    }

    pub fn update_book(&mut self, id: &str, title: &str, language: &str) -> AppResult<BookSummary> {
        let title = require_label(title, "Enter a book or subject name.", 160)?;
        let language = study_language(language)?;
        let changed = self.conn.execute(
            "UPDATE books SET title = ?1, language = ?2, updated_at = ?3 WHERE id = ?4 AND deleted_at IS NULL",
            params![title, language, now_ts(), id],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That book was not found.".into()));
        }
        self.book_summary(id)
    }

    pub fn reorder_books(&mut self, class_id: &str, ordered_ids: &[String]) -> AppResult<()> {
        self.reorder_children("books", "class_id", class_id, ordered_ids)
    }

    pub fn set_book_archived(&mut self, id: &str, archived: bool) -> AppResult<BookSummary> {
        self.set_archived("books", id, archived)?;
        self.book_summary(id)
    }

    pub fn soft_delete_book(&mut self, id: &str) -> AppResult<()> {
        self.soft_delete("books", id, "That book was not found.")
    }

    pub fn restore_book(&mut self, id: &str) -> AppResult<BookSummary> {
        self.restore("books", id, "That book is not in Recently deleted.")?;
        self.book_summary(id)
    }

    pub fn purge_book(&mut self, id: &str, confirmation: &str) -> AppResult<()> {
        self.purge("books", id, confirmation)
    }

    pub fn list_chapters(&self, book_id: &str, include_archived: bool) -> AppResult<Vec<ChapterSummary>> {
        self.ensure_live("books", book_id, "That book was not found.")?;
        let mut stmt = self.conn.prepare(
            "SELECT ch.id, ch.book_id, ch.title, ch.sort_order, ch.archived_at IS NOT NULL,
                (SELECT COUNT(*) FROM topics t WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL),
                (SELECT COUNT(*) FROM topics t JOIN topic_notes n ON n.topic_id = t.id
                    WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL AND length(trim(n.reference_text)) > 0),
                (SELECT COUNT(*) FROM topics t JOIN topic_revision_status r ON r.topic_id = t.id
                    WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL)
             FROM chapters ch
             WHERE ch.book_id = ?1 AND ch.deleted_at IS NULL AND (?2 = 1 OR ch.archived_at IS NULL)
             ORDER BY ch.sort_order, ch.created_at",
        )?;
        let rows = stmt.query_map(params![book_id, include_archived as i64], |row| {
            Ok(ChapterSummary {
                id: row.get(0)?,
                book_id: row.get(1)?,
                title: row.get(2)?,
                sort_order: row.get(3)?,
                archived: row.get(4)?,
                topic_count: row.get(5)?,
                studied_topic_count: row.get(6)?,
                tested_topic_count: row.get(7)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn create_chapter(&mut self, book_id: &str, title: &str) -> AppResult<ChapterSummary> {
        self.ensure_live("books", book_id, "That book was not found.")?;
        let title = require_label(title, "Enter a chapter name.", 180)?;
        let id = new_id();
        let sort = self.next_sort("chapters", "book_id", book_id)?;
        self.conn.execute(
            "INSERT INTO chapters (id, book_id, title, sort_order, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?5)",
            params![id, book_id, title, sort, now_ts()],
        )?;
        self.chapter_summary(&id)
    }

    pub fn update_chapter(&mut self, id: &str, title: &str) -> AppResult<ChapterSummary> {
        let title = require_label(title, "Enter a chapter name.", 180)?;
        let changed = self.conn.execute(
            "UPDATE chapters SET title = ?1, updated_at = ?2 WHERE id = ?3 AND deleted_at IS NULL",
            params![title, now_ts(), id],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That chapter was not found.".into()));
        }
        self.chapter_summary(id)
    }

    pub fn reorder_chapters(&mut self, book_id: &str, ordered_ids: &[String]) -> AppResult<()> {
        self.reorder_children("chapters", "book_id", book_id, ordered_ids)
    }

    pub fn set_chapter_archived(&mut self, id: &str, archived: bool) -> AppResult<ChapterSummary> {
        self.set_archived("chapters", id, archived)?;
        self.chapter_summary(id)
    }

    pub fn soft_delete_chapter(&mut self, id: &str) -> AppResult<()> {
        self.soft_delete("chapters", id, "That chapter was not found.")
    }

    pub fn restore_chapter(&mut self, id: &str) -> AppResult<ChapterSummary> {
        self.restore("chapters", id, "That chapter is not in Recently deleted.")?;
        self.chapter_summary(id)
    }

    pub fn purge_chapter(&mut self, id: &str, confirmation: &str) -> AppResult<()> {
        self.purge("chapters", id, confirmation)
    }

    pub fn list_topics(&self, chapter_id: &str, include_archived: bool) -> AppResult<Vec<TopicSummary>> {
        self.ensure_live("chapters", chapter_id, "That chapter was not found.")?;
        let mut stmt = self.conn.prepare(
            "SELECT t.id, t.chapter_id, t.title, t.language, t.sort_order, t.archived_at IS NOT NULL,
                CASE WHEN n.reference_text IS NOT NULL AND length(trim(n.reference_text)) > 0 THEN 1 ELSE 0 END,
                COALESCE(r.status, 'untested'),
                r.last_score
             FROM topics t
             LEFT JOIN topic_notes n ON n.topic_id = t.id
             LEFT JOIN topic_revision_status r ON r.topic_id = t.id
             WHERE t.chapter_id = ?1 AND t.deleted_at IS NULL AND (?2 = 1 OR t.archived_at IS NULL)
             ORDER BY t.sort_order, t.created_at",
        )?;
        let rows = stmt.query_map(params![chapter_id, include_archived as i64], map_topic)?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn create_topic(&mut self, chapter_id: &str, title: &str, language: &str) -> AppResult<TopicSummary> {
        self.ensure_live("chapters", chapter_id, "That chapter was not found.")?;
        let title = require_label(title, "Enter a topic title.", 180)?;
        let language = study_language(language)?;
        let id = new_id();
        let ts = now_ts();
        let sort = self.next_sort("topics", "chapter_id", chapter_id)?;
        let tx = self.conn.transaction()?;
        tx.execute(
            "INSERT INTO topics (id, chapter_id, title, language, sort_order, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6)",
            params![id, chapter_id, title, language, sort, ts],
        )?;
        tx.execute(
            "INSERT INTO topic_notes (id, topic_id, reference_text, draft_text, language, text_direction, updated_at)
             VALUES (?1, ?2, '', '', ?3, ?4, ?5)",
            params![new_id(), id, language, direction_for_language(&language), ts],
        )?;
        tx.commit()?;
        self.topic_summary(&id)
    }

    pub fn update_topic(&mut self, id: &str, title: &str, language: &str) -> AppResult<TopicSummary> {
        let title = require_label(title, "Enter a topic title.", 180)?;
        let language = study_language(language)?;
        let changed = self.conn.execute(
            "UPDATE topics SET title = ?1, language = ?2, updated_at = ?3 WHERE id = ?4 AND deleted_at IS NULL",
            params![title, language, now_ts(), id],
        )?;
        if changed == 0 {
            return Err(AppError::NotFound("That topic was not found.".into()));
        }
        self.conn.execute(
            "UPDATE topic_notes SET language = ?1, text_direction = ?2, updated_at = ?3 WHERE topic_id = ?4",
            params![language, direction_for_language(&language), now_ts(), id],
        )?;
        self.topic_summary(id)
    }

    pub fn reorder_topics(&mut self, chapter_id: &str, ordered_ids: &[String]) -> AppResult<()> {
        self.reorder_children("topics", "chapter_id", chapter_id, ordered_ids)
    }

    pub fn move_topic(&mut self, topic_id: &str, target_chapter_id: &str) -> AppResult<TopicSummary> {
        self.ensure_live("topics", topic_id, "That topic was not found.")?;
        self.ensure_live("chapters", target_chapter_id, "That chapter was not found.")?;
        let source_student = self.student_of_topic(topic_id)?;
        let target_student = self.student_of_chapter(target_chapter_id)?;
        if source_student != target_student {
            return Err(AppError::Invalid("Move the topic into a chapter that belongs to the same student.".into()));
        }
        let sort = self.next_sort("topics", "chapter_id", target_chapter_id)?;
        self.conn.execute(
            "UPDATE topics SET chapter_id = ?1, sort_order = ?2, updated_at = ?3 WHERE id = ?4",
            params![target_chapter_id, sort, now_ts(), topic_id],
        )?;
        self.topic_summary(topic_id)
    }

    pub fn set_topic_archived(&mut self, id: &str, archived: bool) -> AppResult<TopicSummary> {
        self.set_archived("topics", id, archived)?;
        self.topic_summary(id)
    }

    pub fn soft_delete_topic(&mut self, id: &str) -> AppResult<()> {
        self.soft_delete("topics", id, "That topic was not found.")
    }

    pub fn restore_topic(&mut self, id: &str) -> AppResult<TopicSummary> {
        self.restore("topics", id, "That topic is not in Recently deleted.")?;
        self.topic_summary(id)
    }

    pub fn purge_topic(&mut self, id: &str, confirmation: &str) -> AppResult<()> {
        self.purge("topics", id, confirmation)
    }

    pub fn search_topics(&self, student_id: &str, query: &str) -> AppResult<Vec<TopicHit>> {
        self.ensure_profile(student_id)?;
        let query = query.trim();
        if query.chars().count() < 1 {
            return Ok(Vec::new());
        }
        let pattern = like_pattern(query);
        let mut stmt = self.conn.prepare(
            "SELECT t.id, t.title, t.language, c.id, c.name, b.id, b.title, ch.id, ch.title,
                CASE WHEN n.reference_text IS NOT NULL AND length(trim(n.reference_text)) > 0 THEN 1 ELSE 0 END,
                COALESCE(r.status, 'untested')
             FROM topics t
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             LEFT JOIN topic_notes n ON n.topic_id = t.id
             LEFT JOIN topic_revision_status r ON r.topic_id = t.id
             WHERE c.student_id = ?1
               AND t.deleted_at IS NULL AND ch.deleted_at IS NULL AND b.deleted_at IS NULL AND c.deleted_at IS NULL
               AND (
                    t.title LIKE ?2 ESCAPE '\\'
                    OR IFNULL(n.reference_text, '') LIKE ?2 ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM topic_key_concepts k
                        WHERE k.topic_id = t.id AND (k.content LIKE ?2 ESCAPE '\\' OR k.label LIKE ?2 ESCAPE '\\')
                    )
               )
             ORDER BY c.sort_order, b.sort_order, ch.sort_order, t.sort_order
             LIMIT 100",
        )?;
        let rows = stmt.query_map(params![student_id, pattern], |row| {
            Ok(TopicHit {
                topic_id: row.get(0)?,
                title: row.get(1)?,
                language: row.get(2)?,
                class_id: row.get(3)?,
                class_name: row.get(4)?,
                book_id: row.get(5)?,
                book_title: row.get(6)?,
                chapter_id: row.get(7)?,
                chapter_title: row.get(8)?,
                has_reference: row.get::<_, i64>(9)? == 1,
                revision_status: row.get(10)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn hierarchy(&self, student_id: &str, include_archived: bool) -> AppResult<Vec<ClassNode>> {
        let classes = self.list_classes(student_id, include_archived)?;
        let mut nodes = Vec::new();
        for class in classes {
            let books = self.list_books(&class.id, include_archived)?;
            let mut book_nodes = Vec::new();
            for book in books {
                let chapters = self.list_chapters(&book.id, include_archived)?;
                let mut chapter_nodes = Vec::new();
                for chapter in chapters {
                    let topics = self.list_topics(&chapter.id, include_archived)?;
                    chapter_nodes.push(ChapterNode { chapter, topics });
                }
                book_nodes.push(BookNode { book, chapters: chapter_nodes });
            }
            nodes.push(ClassNode { class, books: book_nodes });
        }
        Ok(nodes)
    }

    pub fn list_trash(&self, student_id: &str) -> AppResult<Vec<TrashItem>> {
        self.ensure_profile(student_id)?;
        let mut items = Vec::new();
        let mut stmt = self.conn.prepare(
            "SELECT id, name, deleted_at FROM classes
             WHERE student_id = ?1 AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(TrashItem {
                kind: "class".into(),
                id: row.get(0)?,
                name: row.get(1)?,
                deleted_at: row.get(2)?,
                parent_label: String::new(),
            })
        })?;
        items.extend(rows.collect::<Result<Vec<_>, _>>()?);
        let mut stmt = self.conn.prepare(
            "SELECT b.id, b.title, b.deleted_at, c.name
             FROM books b JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND b.deleted_at IS NOT NULL AND c.deleted_at IS NULL
             ORDER BY b.deleted_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(TrashItem {
                kind: "book".into(),
                id: row.get(0)?,
                name: row.get(1)?,
                deleted_at: row.get(2)?,
                parent_label: row.get(3)?,
            })
        })?;
        items.extend(rows.collect::<Result<Vec<_>, _>>()?);
        let mut stmt = self.conn.prepare(
            "SELECT ch.id, ch.title, ch.deleted_at, b.title
             FROM chapters ch
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND ch.deleted_at IS NOT NULL AND b.deleted_at IS NULL AND c.deleted_at IS NULL
             ORDER BY ch.deleted_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(TrashItem {
                kind: "chapter".into(),
                id: row.get(0)?,
                name: row.get(1)?,
                deleted_at: row.get(2)?,
                parent_label: row.get(3)?,
            })
        })?;
        items.extend(rows.collect::<Result<Vec<_>, _>>()?);
        let mut stmt = self.conn.prepare(
            "SELECT t.id, t.title, t.deleted_at, ch.title
             FROM topics t
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             WHERE c.student_id = ?1 AND t.deleted_at IS NOT NULL
               AND ch.deleted_at IS NULL AND b.deleted_at IS NULL AND c.deleted_at IS NULL
             ORDER BY t.deleted_at DESC",
        )?;
        let rows = stmt.query_map(params![student_id], |row| {
            Ok(TrashItem {
                kind: "topic".into(),
                id: row.get(0)?,
                name: row.get(1)?,
                deleted_at: row.get(2)?,
                parent_label: row.get(3)?,
            })
        })?;
        items.extend(rows.collect::<Result<Vec<_>, _>>()?);
        Ok(items)
    }

    pub fn get_topic(&self, id: &str) -> AppResult<TopicDetail> {
        let row = self.conn.query_row(
            "SELECT t.id, t.title, t.language, n.text_direction, c.id, c.name, b.id, b.title, ch.id, ch.title,
                    n.reference_text, n.draft_text, n.draft_concepts_json, COALESCE(r.status, 'untested'), r.last_score
             FROM topics t
             JOIN topic_notes n ON n.topic_id = t.id
             JOIN chapters ch ON ch.id = t.chapter_id
             JOIN books b ON b.id = ch.book_id
             JOIN classes c ON c.id = b.class_id
             LEFT JOIN topic_revision_status r ON r.topic_id = t.id
             WHERE t.id = ?1 AND t.deleted_at IS NULL AND ch.deleted_at IS NULL
               AND b.deleted_at IS NULL AND c.deleted_at IS NULL",
            params![id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, String>(9)?,
                    row.get::<_, String>(10)?,
                    row.get::<_, String>(11)?,
                    row.get::<_, String>(12)?,
                    row.get::<_, String>(13)?,
                    row.get::<_, Option<f64>>(14)?,
                ))
            },
        ).map_err(|err| not_found(err, "That topic was not found."))?;
        let concepts = self.concepts_for(&row.0)?;
        let draft_concepts = if row.12.trim().is_empty() {
            Vec::new()
        } else {
            serde_json::from_str(&row.12).unwrap_or_default()
        };
        Ok(TopicDetail {
            id: row.0,
            title: row.1,
            language: row.2,
            text_direction: row.3,
            class_id: row.4,
            class_name: row.5,
            book_id: row.6,
            book_title: row.7,
            chapter_id: row.8,
            chapter_title: row.9,
            reference_text: row.10,
            draft_text: row.11.clone(),
            has_draft: !row.11.trim().is_empty() || !row.12.trim().is_empty(),
            concepts,
            draft_concepts,
            revision_status: row.13,
            last_score: row.14,
        })
    }

    pub fn save_topic_draft(&mut self, id: &str, input: TopicDraftInput) -> AppResult<TopicDetail> {
        self.ensure_live("topics", id, "That topic was not found.")?;
        let title = require_label(&input.title, "Enter a topic title.", 180)?;
        let language = study_language(&input.language)?;
        validate_concepts(&input.concepts)?;
        if input.draft_text.chars().count() > 200_000 {
            return Err(AppError::Invalid("The draft is too long to store.".into()));
        }
        let draft_json = serde_json::to_string(&input.concepts)
            .map_err(|err| AppError::Invalid(err.to_string()))?;
        let ts = now_ts();
        self.conn.execute(
            "UPDATE topics SET title = ?1, language = ?2, updated_at = ?3 WHERE id = ?4",
            params![title, language, ts, id],
        )?;
        self.conn.execute(
            "UPDATE topic_notes
             SET draft_text = ?1, draft_concepts_json = ?2, language = ?3, text_direction = ?4, updated_at = ?5
             WHERE topic_id = ?6",
            params![input.draft_text, draft_json, language, direction_for_language(&language), ts, id],
        )?;
        self.get_topic(id)
    }

    pub fn save_topic(&mut self, id: &str, input: TopicSaveInput) -> AppResult<TopicDetail> {
        self.ensure_live("topics", id, "That topic was not found.")?;
        let title = require_label(&input.title, "Enter a topic title.", 180)?;
        let language = study_language(&input.language)?;
        validate_concepts(&input.concepts)?;
        if input.reference_text.chars().count() > 200_000 {
            return Err(AppError::Invalid("The reference note is too long to store.".into()));
        }
        let ts = now_ts();
        let tx = self.conn.transaction()?;
        tx.execute(
            "UPDATE topics SET title = ?1, language = ?2, updated_at = ?3 WHERE id = ?4",
            params![title, language, ts, id],
        )?;
        tx.execute(
            "UPDATE topic_notes
             SET reference_text = ?1, draft_text = '', draft_concepts_json = '', language = ?2,
                 text_direction = ?3, updated_at = ?4
             WHERE topic_id = ?5",
            params![input.reference_text, language, direction_for_language(&language), ts, id],
        )?;
        tx.execute("DELETE FROM topic_key_concepts WHERE topic_id = ?1", params![id])?;
        for (index, concept) in input.concepts.iter().enumerate() {
            tx.execute(
                "INSERT INTO topic_key_concepts
                 (id, topic_id, kind, label, content, aliases, sort_order, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?8)",
                params![
                    new_id(),
                    id,
                    concept.kind,
                    concept.label.trim(),
                    concept.content.trim(),
                    concept.aliases.trim(),
                    index as i64,
                    ts
                ],
            )?;
        }
        tx.commit()?;
        self.get_topic(id)
    }

    pub(crate) fn concepts_for(&self, topic_id: &str) -> AppResult<Vec<ConceptRef>> {
        let mut stmt = self.conn.prepare(
            "SELECT kind, label, content, aliases FROM topic_key_concepts
             WHERE topic_id = ?1 ORDER BY sort_order, created_at",
        )?;
        let rows = stmt.query_map(params![topic_id], |row| {
            Ok(ConceptRef {
                kind: row.get(0)?,
                label: row.get(1)?,
                content: row.get(2)?,
                aliases: row.get(3)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub(crate) fn ensure_profile(&self, student_id: &str) -> AppResult<()> {
        let found: Option<String> = self
            .conn
            .query_row(
                "SELECT id FROM student_profiles WHERE id = ?1",
                params![student_id],
                |row| row.get(0),
            )
            .optional()?;
        found
            .map(|_| ())
            .ok_or_else(|| AppError::NotFound("Create a student profile first.".into()))
    }

    fn class_summary(&self, id: &str) -> AppResult<ClassSummary> {
        let student_id: String = self
            .conn
            .query_row("SELECT student_id FROM classes WHERE id = ?1", params![id], |row| row.get(0))
            .map_err(|err| not_found(err, "That class was not found."))?;
        self.list_classes(&student_id, true)?
            .into_iter()
            .find(|c| c.id == id)
            .ok_or_else(|| AppError::NotFound("That class was not found.".into()))
    }

    fn book_summary(&self, id: &str) -> AppResult<BookSummary> {
        self.conn
            .query_row(
                "SELECT b.id, b.class_id, b.title, b.language, b.sort_order, b.archived_at IS NOT NULL,
                    (SELECT COUNT(*) FROM chapters ch WHERE ch.book_id = b.id AND ch.deleted_at IS NULL),
                    (SELECT COUNT(*) FROM topics t JOIN chapters ch ON ch.id = t.chapter_id
                        WHERE ch.book_id = b.id AND t.deleted_at IS NULL AND ch.deleted_at IS NULL)
                 FROM books b WHERE b.id = ?1 AND b.deleted_at IS NULL",
                params![id],
                map_book,
            )
            .map_err(|err| not_found(err, "That book was not found."))
    }

    fn chapter_summary(&self, id: &str) -> AppResult<ChapterSummary> {
        self.conn
            .query_row(
                "SELECT ch.id, ch.book_id, ch.title, ch.sort_order, ch.archived_at IS NOT NULL,
                    (SELECT COUNT(*) FROM topics t WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL),
                    (SELECT COUNT(*) FROM topics t JOIN topic_notes n ON n.topic_id = t.id
                        WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL AND length(trim(n.reference_text)) > 0),
                    (SELECT COUNT(*) FROM topics t JOIN topic_revision_status r ON r.topic_id = t.id
                        WHERE t.chapter_id = ch.id AND t.deleted_at IS NULL)
                 FROM chapters ch WHERE ch.id = ?1 AND ch.deleted_at IS NULL",
                params![id],
                |row| {
                    Ok(ChapterSummary {
                        id: row.get(0)?,
                        book_id: row.get(1)?,
                        title: row.get(2)?,
                        sort_order: row.get(3)?,
                        archived: row.get(4)?,
                        topic_count: row.get(5)?,
                        studied_topic_count: row.get(6)?,
                        tested_topic_count: row.get(7)?,
                    })
                },
            )
            .map_err(|err| not_found(err, "That chapter was not found."))
    }

    fn topic_summary(&self, id: &str) -> AppResult<TopicSummary> {
        self.conn
            .query_row(
                "SELECT t.id, t.chapter_id, t.title, t.language, t.sort_order, t.archived_at IS NOT NULL,
                    CASE WHEN n.reference_text IS NOT NULL AND length(trim(n.reference_text)) > 0 THEN 1 ELSE 0 END,
                    COALESCE(r.status, 'untested'), r.last_score
                 FROM topics t
                 LEFT JOIN topic_notes n ON n.topic_id = t.id
                 LEFT JOIN topic_revision_status r ON r.topic_id = t.id
                 WHERE t.id = ?1 AND t.deleted_at IS NULL",
                params![id],
                map_topic,
            )
            .map_err(|err| not_found(err, "That topic was not found."))
    }

    fn next_sort(&self, table: &str, parent_col: &str, parent_id: &str) -> AppResult<i64> {
        let (table, parent_col) = whitelist(table, parent_col)?;
        let sql = format!(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table} WHERE {parent_col} = ?1 AND deleted_at IS NULL"
        );
        let value: i64 = self.conn.query_row(&sql, params![parent_id], |row| row.get(0))?;
        Ok(value)
    }

    fn reorder_children(
        &mut self,
        table: &str,
        parent_col: &str,
        parent_id: &str,
        ordered_ids: &[String],
    ) -> AppResult<()> {
        let (table, parent_col) = whitelist(table, parent_col)?;
        let sql = format!(
            "SELECT id FROM {table} WHERE {parent_col} = ?1 AND deleted_at IS NULL ORDER BY sort_order"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let existing: Vec<String> = stmt
            .query_map(params![parent_id], |row| row.get(0))?
            .collect::<Result<Vec<_>, _>>()?;
        let mut left = existing.clone();
        let mut right = ordered_ids.to_vec();
        left.sort();
        right.sort();
        if left != right {
            return Err(AppError::Invalid(
                "Include every item once when changing the order.".into(),
            ));
        }
        let ts = now_ts();
        let update = format!("UPDATE {table} SET sort_order = ?1, updated_at = ?2 WHERE id = ?3");
        for (index, id) in ordered_ids.iter().enumerate() {
            self.conn.execute(&update, params![index as i64, ts, id])?;
        }
        Ok(())
    }

    fn set_archived(&mut self, table: &str, id: &str, archived: bool) -> AppResult<()> {
        let (table, _) = whitelist(table, "student_id")?;
        let ts = now_ts();
        let archived_at = if archived { Some(ts.clone()) } else { None };
        let sql = format!(
            "UPDATE {table} SET archived_at = ?1, updated_at = ?2 WHERE id = ?3 AND deleted_at IS NULL"
        );
        let changed = self.conn.execute(&sql, params![archived_at, ts, id])?;
        if changed == 0 {
            return Err(AppError::NotFound("That item was not found.".into()));
        }
        Ok(())
    }

    fn soft_delete(&mut self, table: &str, id: &str, missing: &str) -> AppResult<()> {
        let (table, _) = whitelist(table, "student_id")?;
        let ts = now_ts();
        let sql = format!(
            "UPDATE {table} SET deleted_at = ?1, updated_at = ?1 WHERE id = ?2 AND deleted_at IS NULL"
        );
        let changed = self.conn.execute(&sql, params![ts, id])?;
        if changed == 0 {
            return Err(AppError::NotFound(missing.into()));
        }
        Ok(())
    }

    fn restore(&mut self, table: &str, id: &str, missing: &str) -> AppResult<()> {
        let (table, _) = whitelist(table, "student_id")?;
        let sql = format!(
            "UPDATE {table} SET deleted_at = NULL, updated_at = ?1 WHERE id = ?2 AND deleted_at IS NOT NULL"
        );
        let changed = self.conn.execute(&sql, params![now_ts(), id])?;
        if changed == 0 {
            return Err(AppError::NotFound(missing.into()));
        }
        Ok(())
    }

    fn purge(&mut self, table: &str, id: &str, confirmation: &str) -> AppResult<()> {
        if confirmation != "DELETE" {
            return Err(AppError::Invalid(
                "Type DELETE to remove this item permanently.".into(),
            ));
        }
        let (table, _) = whitelist(table, "student_id")?;
        let sql = format!("DELETE FROM {table} WHERE id = ?1 AND deleted_at IS NOT NULL");
        let changed = self.conn.execute(&sql, params![id])?;
        if changed == 0 {
            return Err(AppError::NotFound(
                "Move the item to Recently deleted before removing it permanently.".into(),
            ));
        }
        Ok(())
    }

    fn ensure_live(&self, table: &str, id: &str, missing: &str) -> AppResult<()> {
        let (table, _) = whitelist(table, "student_id")?;
        let sql = format!("SELECT id FROM {table} WHERE id = ?1 AND deleted_at IS NULL");
        let found: Option<String> = self
            .conn
            .query_row(&sql, params![id], |row| row.get(0))
            .optional()?;
        found.map(|_| ()).ok_or_else(|| AppError::NotFound(missing.into()))
    }

    pub(crate) fn student_of_chapter(&self, chapter_id: &str) -> AppResult<String> {
        self.conn
            .query_row(
                "SELECT c.student_id FROM chapters ch
                 JOIN books b ON b.id = ch.book_id
                 JOIN classes c ON c.id = b.class_id
                 WHERE ch.id = ?1",
                params![chapter_id],
                |row| row.get(0),
            )
            .map_err(|err| not_found(err, "That chapter was not found."))
    }

    pub(crate) fn student_of_topic(&self, topic_id: &str) -> AppResult<String> {
        self.conn
            .query_row(
                "SELECT c.student_id FROM topics t
                 JOIN chapters ch ON ch.id = t.chapter_id
                 JOIN books b ON b.id = ch.book_id
                 JOIN classes c ON c.id = b.class_id
                 WHERE t.id = ?1",
                params![topic_id],
                |row| row.get(0),
            )
            .map_err(|err| not_found(err, "That topic was not found."))
    }

    pub(crate) fn set_revision(
        &mut self,
        student_id: &str,
        topic_id: &str,
        status: &str,
        score: Option<f64>,
        source: &str,
    ) -> AppResult<()> {
        let previous: Option<String> = self
            .conn
            .query_row(
                "SELECT status FROM topic_revision_status WHERE topic_id = ?1",
                params![topic_id],
                |row| row.get(0),
            )
            .optional()?;
        let ts = now_ts();
        self.conn.execute(
            "INSERT INTO revision_events
             (id, student_id, topic_id, previous_status, new_status, score, source, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![new_id(), student_id, topic_id, previous, status, score, source, ts],
        )?;
        self.conn.execute(
            "INSERT INTO topic_revision_status (topic_id, student_id, status, last_score, last_source, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(topic_id) DO UPDATE SET
               status = excluded.status,
               last_score = COALESCE(excluded.last_score, topic_revision_status.last_score),
               last_source = excluded.last_source,
               student_id = excluded.student_id,
               updated_at = excluded.updated_at",
            params![topic_id, student_id, status, score, source, ts],
        )?;
        Ok(())
    }
}

fn map_book(row: &rusqlite::Row<'_>) -> rusqlite::Result<BookSummary> {
    Ok(BookSummary {
        id: row.get(0)?,
        class_id: row.get(1)?,
        title: row.get(2)?,
        language: row.get(3)?,
        sort_order: row.get(4)?,
        archived: row.get(5)?,
        chapter_count: row.get(6)?,
        topic_count: row.get(7)?,
    })
}

fn map_topic(row: &rusqlite::Row<'_>) -> rusqlite::Result<TopicSummary> {
    Ok(TopicSummary {
        id: row.get(0)?,
        chapter_id: row.get(1)?,
        title: row.get(2)?,
        language: row.get(3)?,
        sort_order: row.get(4)?,
        archived: row.get(5)?,
        has_reference: row.get::<_, i64>(6)? == 1,
        revision_status: row.get(7)?,
        last_score: row.get(8)?,
    })
}

fn study_language(language: &str) -> AppResult<String> {
    match normalize_language(language).map_err(AppError::Invalid)? {
        "auto" => Err(AppError::Invalid("Choose English or Urdu.".into())),
        other => Ok(other.to_string()),
    }
}

fn validate_concepts(concepts: &[ConceptRef]) -> AppResult<()> {
    for concept in concepts {
        if !matches!(
            concept.kind.as_str(),
            "definition" | "fact" | "keyword" | "formula" | "example" | "expected_point"
        ) {
            return Err(AppError::Invalid(
                "Each note item needs a type: definition, fact, keyword, formula, example, or expected point.".into(),
            ));
        }
        if concept.content.trim().is_empty() {
            return Err(AppError::Invalid("Each note item needs some text.".into()));
        }
    }
    Ok(())
}

fn whitelist<'a>(table: &'a str, parent_col: &'a str) -> AppResult<(&'a str, &'a str)> {
    let table_ok = matches!(table, "classes" | "books" | "chapters" | "topics");
    let parent_ok = matches!(
        parent_col,
        "student_id" | "class_id" | "book_id" | "chapter_id"
    );
    if table_ok && parent_ok {
        Ok((table, parent_col))
    } else {
        Err(AppError::Invalid("That item could not be updated.".into()))
    }
}
