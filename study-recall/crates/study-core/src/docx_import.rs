use std::io::Cursor;
#[cfg(test)]
use std::io::Write;

use serde::{Deserialize, Serialize};
#[cfg(test)]
use zip::write::SimpleFileOptions;
use zip::ZipArchive;
#[cfg(test)]
use zip::{CompressionMethod, ZipWriter};

use crate::error::{AppError, AppResult};
use crate::hierarchy::TopicSaveInput;
use crate::Database;

const MAX_DOCX_BYTES: usize = 20 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ImportedTopic {
    pub title: String,
    pub body: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ImportedChapter {
    pub title: String,
    pub topics: Vec<ImportedTopic>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportReport {
    pub chapters_created: i64,
    pub chapters_reused: i64,
    pub topics_created: i64,
    pub notes_saved: i64,
    pub notes_left_unchanged: i64,
    pub warnings: Vec<String>,
    pub chapters: Vec<ImportedChapter>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Role {
    Chapter,
    Topic,
    Body,
}

struct Paragraph {
    style: String,
    outline: Option<i32>,
    text: String,
    /// Bold letters at the start of the paragraph, before any text that is not bold.
    bold_lead: String,
    entirely_bold: bool,
    saw_plain: bool,
}

/// Reads a .docx file and places each topic under the chapter named in the document.
pub fn import_word_into_book(db: &mut Database, book_id: &str, bytes: &[u8]) -> AppResult<ImportReport> {
    if bytes.len() > MAX_DOCX_BYTES {
        return Err(AppError::Invalid(
            "That Word file is larger than 20 MB. Split it and import each part.".into(),
        ));
    }
    let fallback = if db.book_language(book_id)? == "ur" { "ur" } else { "en" };
    let (chapters, mut warnings) = parse_docx(bytes).map_err(AppError::Invalid)?;
    if chapters.is_empty() {
        return Err(AppError::Invalid(
            "No chapters or topics were found. Start a chapter with “Chapter 1” or “Unit 1”, or make each topic a bold heading on its own line.".into(),
        ));
    }
    let mut report = ImportReport {
        chapters_created: 0,
        chapters_reused: 0,
        topics_created: 0,
        notes_saved: 0,
        notes_left_unchanged: 0,
        warnings: Vec::new(),
        chapters: chapters.clone(),
    };
    let mut known = db.list_chapters(book_id, false)?;
    for chapter in chapters {
        let key = shelf_key(&chapter.title);
        let chapter_id = if let Some(found) = known.iter().find(|item| shelf_key(&item.title) == key) {
            report.chapters_reused += 1;
            found.id.clone()
        } else {
            let created = db.create_chapter(book_id, &chapter.title)?;
            report.chapters_created += 1;
            let id = created.id.clone();
            known.push(created);
            id
        };
        let mut topics = db.list_topics(&chapter_id, false)?;
        for topic in chapter.topics {
            let topic_key = shelf_key(&topic.title);
            let language = language_for(&topic.body, fallback);
            if let Some(position) = topics.iter().position(|item| shelf_key(&item.title) == topic_key) {
                if topics[position].has_reference {
                    report.notes_left_unchanged += 1;
                    warnings.push(format!(
                        "“{}” in “{}” already had notes, so the imported text was left unused.",
                        topic.title, chapter.title
                    ));
                } else if !topic.body.trim().is_empty() {
                    let title = topics[position].title.clone();
                    let id = topics[position].id.clone();
                    db.save_topic(
                        &id,
                        TopicSaveInput {
                            title,
                            language,
                            reference_text: topic.body,
                            concepts: Vec::new(),
                        },
                    )?;
                    topics[position].has_reference = true;
                    report.notes_saved += 1;
                }
            } else {
                let created = db.create_topic(&chapter_id, &topic.title, &language)?;
                report.topics_created += 1;
                let mut stored = created;
                if !topic.body.trim().is_empty() {
                    db.save_topic(
                        &stored.id,
                        TopicSaveInput {
                            title: stored.title.clone(),
                            language,
                            reference_text: topic.body,
                            concepts: Vec::new(),
                        },
                    )?;
                    stored.has_reference = true;
                    report.notes_saved += 1;
                }
                topics.push(stored);
            }
        }
    }
    report.warnings = warnings;
    Ok(report)
}

pub fn parse_docx(bytes: &[u8]) -> Result<(Vec<ImportedChapter>, Vec<String>), String> {
    let mut archive = ZipArchive::new(Cursor::new(bytes)).map_err(|_| {
        "That file is not a Word .docx document. Save it from Word as a .docx file and try again.".to_string()
    })?;
    let mut document = archive
        .by_name("word/document.xml")
        .map_err(|_| "That Word file has no readable document. Save it again as .docx.".to_string())?;
    let mut xml = String::new();
    std::io::Read::read_to_string(&mut document, &mut xml)
        .map_err(|_| "The Word document could not be read.".to_string())?;
    let paragraphs = read_paragraphs(&xml)?;
    organize(paragraphs)
}

fn organize(paragraphs: Vec<Paragraph>) -> Result<(Vec<ImportedChapter>, Vec<String>), String> {
    let mut warnings = Vec::new();
    let mut chapters: Vec<DraftChapter> = Vec::new();
    let mut index: Option<usize> = None;
    let mut topic_index: Option<usize> = None;
    let mut warned_early = false;
    let mut fresh_topic = false;
    let next_is_bold = next_bold_flags(&paragraphs);
    for (at, paragraph) in paragraphs.iter().enumerate() {
        let text = collapse(&paragraph.text);
        if text.is_empty() {
            continue;
        }
        match role_of(paragraph, &text, next_is_bold[at], fresh_topic) {
            Role::Chapter => {
                let title = clean_chapter_title(&text);
                chapters.push(DraftChapter { title, topics: Vec::new(), loose: String::new() });
                index = Some(chapters.len() - 1);
                topic_index = None;
                fresh_topic = false;
            }
            Role::Topic => {
                let (title, inline) = topic_title_and_inline(paragraph, &text, next_is_bold[at]);
                if index.is_none() {
                    if inline.trim().is_empty() {
                        fresh_topic = false;
                        continue;
                    }
                    chapters.push(DraftChapter {
                        title: "Imported notes".into(),
                        topics: Vec::new(),
                        loose: String::new(),
                    });
                    index = Some(0);
                    if !warned_early {
                        warnings.push(
                            "Some topics appeared before the first chapter, so they were placed in “Imported notes”."
                                .into(),
                        );
                        warned_early = true;
                    }
                }
                let chapter = &mut chapters[index.expect("chapter")];
                chapter.topics.push(ImportedTopic { title, body: String::new() });
                topic_index = Some(chapter.topics.len() - 1);
                fresh_topic = true;
                if !inline.trim().is_empty() {
                    append_body(&mut chapter.topics[topic_index.expect("topic")].body, &inline);
                    fresh_topic = false;
                }
            }
            Role::Body => {
                fresh_topic = false;
                if let Some(chapter_at) = index {
                    if let Some(topic_at) = topic_index {
                        append_body(&mut chapters[chapter_at].topics[topic_at].body, &text);
                    } else {
                        append_body(&mut chapters[chapter_at].loose, &text);
                    }
                } else {
                    warnings.push(format!("This line was before any chapter and was not imported: {text}"));
                }
            }
        }
    }
    let mut finished = Vec::new();
    for mut chapter in chapters {
        if chapter.topics.is_empty() && !chapter.loose.trim().is_empty() {
            warnings.push(format!(
                "“{}” had no topic headings, so its text was saved as one topic with the chapter name.",
                chapter.title
            ));
            chapter.topics.push(ImportedTopic {
                title: chapter.title.clone(),
                body: chapter.loose,
            });
        } else if !chapter.loose.trim().is_empty() {
            chapter.topics.insert(
                0,
                ImportedTopic {
                    title: "Chapter notes".into(),
                    body: chapter.loose,
                },
            );
        }
        chapter.topics.retain(|topic| !topic.title.trim().is_empty());
        if !chapter.topics.is_empty() {
            finished.push(ImportedChapter {
                title: chapter.title,
                topics: chapter.topics,
            });
        }
    }
    if finished.len() > 200 {
        return Err("That document has more than 200 chapters. Split it into smaller Word files.".into());
    }
    let topic_count: usize = finished.iter().map(|chapter| chapter.topics.len()).sum();
    if topic_count > 2000 {
        return Err("That document has more than 2000 topics. Split it into smaller Word files.".into());
    }
    Ok((finished, warnings))
}

struct DraftChapter {
    title: String,
    topics: Vec<ImportedTopic>,
    loose: String,
}

fn role_of(paragraph: &Paragraph, text: &str, next_is_bold: bool, fresh_topic: bool) -> Role {
    if looks_like_chapter(text) {
        return Role::Chapter;
    }
    if looks_like_topic(text) {
        return Role::Topic;
    }
    let style = paragraph.style.to_ascii_lowercase().replace([' ', '_', '-'], "");
    if style.contains("heading1") || style == "title" || paragraph.outline == Some(0) {
        return Role::Chapter;
    }
    if style.contains("heading2")
        || style.contains("heading3")
        || style.contains("heading4")
        || matches!(paragraph.outline, Some(1) | Some(2) | Some(3))
    {
        return Role::Topic;
    }
    if let Some((_, inline)) = heading_from_bold(paragraph, text, next_is_bold) {
        if fresh_topic && !paragraph.entirely_bold && explanatory_sentence(&paragraph.bold_lead) && !inline.trim().is_empty()
        {
            return Role::Body;
        }
        return Role::Topic;
    }
    Role::Body
}

fn topic_title_and_inline(paragraph: &Paragraph, text: &str, next_is_bold: bool) -> (String, String) {
    if looks_like_topic(text) {
        return (clean_topic_title(text), String::new());
    }
    if let Some(split) = heading_from_bold(paragraph, text, next_is_bold) {
        return split;
    }
    (clean_topic_title(text), String::new())
}

/// A bold label on its own, or the bold start of a line, is a topic heading.
fn heading_from_bold(paragraph: &Paragraph, text: &str, next_is_bold: bool) -> Option<(String, String)> {
    if paragraph.entirely_bold {
        if starts_with_lowercase(text) || is_enumerator_only(text) || text.chars().count() > 90 {
            return None;
        }
        if let Some(split) = split_bold_label(text) {
            return Some(split);
        }
        let ends_colon = text.ends_with(':') || text.ends_with(":-");
        if next_is_bold && !ends_colon && !standalone_title(text) {
            return None;
        }
        let title = clean_heading_title(text);
        if title.chars().count() < 2 {
            return None;
        }
        return Some((title, String::new()));
    }
    let lead = collapse(&paragraph.bold_lead);
    if lead.chars().count() < 2 || lead.chars().count() > 80 || is_enumerator_only(&lead) {
        return None;
    }
    if lead.split_whitespace().count() > 6 && lead.ends_with(['.', '۔']) {
        return None;
    }
    let inline = text.strip_prefix(lead.as_str()).unwrap_or("").trim().to_string();
    let title = clean_heading_title(&lead);
    if title.chars().count() < 2 {
        return None;
    }
    Some((title, collapse(&inline)))
}

fn split_bold_label(text: &str) -> Option<(String, String)> {
    let (left, right) = text.split_once(':')?;
    let left = left.trim();
    let right = right.trim();
    if right.is_empty() {
        return None;
    }
    let words = left.split_whitespace().count();
    if (2..=10).contains(&words) && left.chars().count() <= 60 {
        let title = clean_heading_title(left);
        if title.chars().count() < 2 {
            return None;
        }
        return Some((title, right.to_string()));
    }
    None
}

fn standalone_title(text: &str) -> bool {
    let periods = text.chars().filter(|ch| *ch == '.' || *ch == '۔').count();
    if periods > 1 || text.contains(',') {
        return false;
    }
    let core = text.trim().trim_end_matches(|ch: char| matches!(ch, '.' | ':' | ';' | '-' | '–' | '—'));
    let words = core.split_whitespace().count();
    (1..=14).contains(&words) && core.chars().count() <= 80
}

fn starts_with_lowercase(text: &str) -> bool {
    text.chars().find(|ch| ch.is_alphabetic()).map(|ch| ch.is_lowercase()).unwrap_or(false)
}

fn is_enumerator_only(text: &str) -> bool {
    let trimmed = text
        .trim()
        .trim_end_matches(|ch: char| matches!(ch, ':' | '.' | ')' | '-' | '–' | '—' | ';'))
        .trim();
    let lower = trimmed.to_lowercase();
    let lower = lower
        .strip_prefix("number ")
        .or_else(|| lower.strip_prefix("no. "))
        .or_else(|| lower.strip_prefix("no "))
        .unwrap_or(&lower)
        .trim();
    if lower.is_empty() {
        return true;
    }
    const WORDS: &[&str] = &[
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    ];
    if WORDS.contains(&lower) {
        return true;
    }
    if lower.chars().all(|ch| ch.is_ascii_digit()) {
        return true;
    }
    lower.chars().count() == 1 && lower.chars().next().is_some_and(|ch| ch.is_ascii_alphabetic())
}

fn explanatory_sentence(lead: &str) -> bool {
    let collapsed = collapse(lead);
    if collapsed.split_whitespace().count() < 4 {
        return false;
    }
    if !(collapsed.ends_with('.') || collapsed.ends_with('۔')) {
        return false;
    }
    let padded = format!(" {} ", collapsed.to_lowercase());
    [" is ", " are ", " was ", " were ", " called ", " known "]
        .iter()
        .any(|word| padded.contains(word))
}

fn clean_heading_title(text: &str) -> String {
    let trimmed = text
        .trim()
        .trim_end_matches(|ch: char| matches!(ch, '.' | ':' | ';' | '-' | '–' | '—'))
        .trim();
    limit_title(if trimmed.is_empty() { text.trim() } else { trimmed })
}

fn clean_chapter_title(text: &str) -> String {
    let collapsed = collapse(text);
    let trimmed = collapsed
        .trim()
        .trim_end_matches(|ch: char| matches!(ch, ':' | '-' | '–' | '—' | '.'))
        .trim();
    limit_title(if trimmed.is_empty() { collapsed.trim() } else { trimmed })
}

fn next_bold_flags(paragraphs: &[Paragraph]) -> Vec<bool> {
    let mut flags = vec![false; paragraphs.len()];
    let mut upcoming = false;
    for index in (0..paragraphs.len()).rev() {
        flags[index] = upcoming;
        if !collapse(&paragraphs[index].text).is_empty() {
            upcoming = paragraphs[index].entirely_bold;
        }
    }
    flags
}

fn looks_like_chapter(text: &str) -> bool {
    let lower = text.trim().to_lowercase();
    lower.starts_with("chapter ")
        || lower.starts_with("chapter:")
        || lower.starts_with("unit ")
        || lower.starts_with("unit:")
        || lower.starts_with("lesson ")
        || lower.starts_with("lesson:")
        || text.trim().starts_with("باب")
        || text.trim().starts_with("سبق")
}

fn looks_like_topic(text: &str) -> bool {
    let lower = text.trim().to_lowercase();
    lower.starts_with("topic ")
        || lower.starts_with("topic:")
        || lower.starts_with("topic.")
        || text.trim().starts_with("موضوع")
}

fn clean_topic_title(text: &str) -> String {
    let trimmed = text.trim();
    let lower = trimmed.to_lowercase();
    let rest = if lower.starts_with("topic") {
        trimmed.get("topic".len()..).unwrap_or(trimmed)
    } else if trimmed.starts_with("موضوع") {
        trimmed.get("موضوع".len()..).unwrap_or(trimmed)
    } else {
        return limit_title(trimmed);
    };
    let rest = rest.trim_start_matches(|ch: char| ch.is_ascii_digit() || ch.is_whitespace() || matches!(ch, ':' | '.' | '-' | '–' | '—' | ')'));
    let title = rest.trim();
    if title.is_empty() { limit_title(trimmed) } else { limit_title(title) }
}

fn limit_title(text: &str) -> String {
    let collapsed = collapse(text);
    collapsed.chars().take(180).collect()
}

fn append_body(target: &mut String, text: &str) {
    if target.chars().count() > 200_000 {
        return;
    }
    if !target.is_empty() {
        target.push_str("\n\n");
    }
    target.push_str(text);
    if target.chars().count() > 200_000 {
        let end = target.char_indices().nth(200_000).map(|(index, _)| index).unwrap_or(target.len());
        target.truncate(end);
    }
}

fn collapse(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn shelf_key(title: &str) -> String {
    collapse(title).to_lowercase()
}

fn language_for(text: &str, fallback: &str) -> String {
    let letters = text.chars().filter(|ch| ch.is_alphabetic()).count();
    let arabic = text.chars().filter(|ch| ('\u{0600}'..='\u{06FF}').contains(ch)).count();
    if letters > 0 && arabic * 3 >= letters { "ur".into() } else { fallback.into() }
}

fn read_paragraphs(xml: &str) -> Result<Vec<Paragraph>, String> {
    use quick_xml::events::Event;
    use quick_xml::Reader;
    let mut reader = Reader::from_str(xml);
    let mut buf = Vec::new();
    let mut paragraphs = Vec::new();
    let mut current: Option<Paragraph> = None;
    let mut in_text = false;
    let mut in_run = false;
    let mut in_run_props = false;
    let mut run_props_for_run = false;
    let mut paragraph_bold = false;
    let mut run_bold = false;
    let mut run_props_bold: Option<bool> = None;
    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(event)) => {
                let name = local_name(event.name().as_ref());
                if name == "p" {
                    current = Some(Paragraph {
                        style: String::new(),
                        outline: None,
                        text: String::new(),
                        bold_lead: String::new(),
                        entirely_bold: false,
                        saw_plain: false,
                    });
                    paragraph_bold = false;
                    run_bold = false;
                    in_run = false;
                    in_run_props = false;
                } else if name == "r" {
                    in_run = true;
                    run_bold = paragraph_bold;
                } else if name == "rpr" {
                    in_run_props = true;
                    run_props_for_run = in_run;
                    run_props_bold = None;
                } else if name == "b" || name == "bcs" {
                    note_bold(&event, in_run_props, &mut run_props_bold);
                } else if name == "pstyle" {
                    if let Some(paragraph) = current.as_mut() {
                        paragraph.style = attr_local(&event, "val");
                    }
                } else if name == "outlinelvl" {
                    if let Some(paragraph) = current.as_mut() {
                        paragraph.outline = attr_local(&event, "val").parse().ok();
                    }
                } else if name == "t" {
                    in_text = true;
                } else if name == "tab" || name == "br" || name == "cr" {
                    push_piece(current.as_mut(), if name == "tab" { " " } else { "\n" }, run_bold);
                }
            }
            Ok(Event::Empty(event)) => {
                let name = local_name(event.name().as_ref());
                if name == "b" || name == "bcs" {
                    note_bold(&event, in_run_props, &mut run_props_bold);
                } else if name == "tab" || name == "br" || name == "cr" {
                    push_piece(current.as_mut(), if name == "tab" { " " } else { "\n" }, run_bold);
                } else if name == "pstyle" {
                    if let Some(paragraph) = current.as_mut() {
                        paragraph.style = attr_local(&event, "val");
                    }
                } else if name == "outlinelvl" {
                    if let Some(paragraph) = current.as_mut() {
                        paragraph.outline = attr_local(&event, "val").parse().ok();
                    }
                }
            }
            Ok(Event::Text(event)) => {
                if in_text {
                    let piece = event.unescape().unwrap_or_default();
                    push_piece(current.as_mut(), &piece, run_bold);
                }
            }
            Ok(Event::End(event)) => {
                let name = local_name(event.name().as_ref());
                if name == "t" {
                    in_text = false;
                } else if name == "rpr" && in_run_props {
                    if let Some(is_bold) = run_props_bold {
                        if run_props_for_run {
                            run_bold = is_bold;
                        } else {
                            paragraph_bold = is_bold;
                        }
                    }
                    in_run_props = false;
                } else if name == "r" {
                    in_run = false;
                    run_bold = paragraph_bold;
                } else if name == "p" {
                    if let Some(mut paragraph) = current.take() {
                        paragraph.entirely_bold = !paragraph.saw_plain && !paragraph.bold_lead.trim().is_empty();
                        if !paragraph.text.trim().is_empty() {
                            paragraphs.push(paragraph);
                        }
                    }
                }
            }
            Ok(Event::Eof) => break,
            Err(err) => return Err(format!("The Word document could not be read: {err}")),
            _ => {}
        }
        buf.clear();
    }
    Ok(paragraphs)
}

fn note_bold(event: &quick_xml::events::BytesStart<'_>, in_run_props: bool, run_props_bold: &mut Option<bool>) {
    if !in_run_props {
        return;
    }
    let value = attr_local(event, "val").to_ascii_lowercase();
    let on = !matches!(value.as_str(), "0" | "false" | "off");
    *run_props_bold = Some(run_props_bold.unwrap_or(false) || on);
}

fn push_piece(paragraph: Option<&mut Paragraph>, piece: &str, bold: bool) {
    let Some(paragraph) = paragraph else {
        return;
    };
    if piece.is_empty() {
        return;
    }
    if bold && !paragraph.saw_plain {
        paragraph.bold_lead.push_str(piece);
    } else {
        paragraph.saw_plain = true;
    }
    paragraph.text.push_str(piece);
}

fn local_name(name: &[u8]) -> String {
    let raw = String::from_utf8_lossy(name);
    raw.rsplit(':').next().unwrap_or(&raw).to_ascii_lowercase()
}

fn attr_local(event: &quick_xml::events::BytesStart<'_>, wanted: &str) -> String {
    for attribute in event.attributes().flatten() {
        let key = String::from_utf8_lossy(attribute.key.as_ref());
        let local = key.rsplit(':').next().unwrap_or(&key);
        if local.eq_ignore_ascii_case(wanted) {
            return attribute.unescape_value().unwrap_or_default().to_string();
        }
    }
    String::new()
}

#[cfg(test)]
fn sample_docx(paragraphs: &[(&str, &str)]) -> Vec<u8> {
    let mut body = String::new();
    for (style, text) in paragraphs {
        let escaped = text
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;");
        if style.is_empty() {
            body.push_str(&format!(
                r#"<w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>"#
            ));
        } else {
            body.push_str(&format!(
                r#"<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{escaped}</w:t></w:r></w:p>"#
            ));
        }
    }
    let xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>"#
    );
    let mut cursor = Cursor::new(Vec::new());
    {
        let mut zip = ZipWriter::new(&mut cursor);
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        zip.start_file("word/document.xml", options).unwrap();
        zip.write_all(xml.as_bytes()).unwrap();
        zip.finish().unwrap();
    }
    cursor.into_inner()
}

#[cfg(test)]
fn docx_runs(paragraphs: &[Vec<(&str, bool)>]) -> Vec<u8> {
    let mut body = String::new();
    for runs in paragraphs {
        body.push_str("<w:p>");
        for (text, bold) in runs {
            let escaped = text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
            if *bold {
                body.push_str(&format!(
                    r#"<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{escaped}</w:t></w:r>"#
                ));
            } else {
                body.push_str(&format!(
                    r#"<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r>"#
                ));
            }
        }
        body.push_str("</w:p>");
    }
    let xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>"#
    );
    let mut cursor = Cursor::new(Vec::new());
    {
        let mut zip = ZipWriter::new(&mut cursor);
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        zip.start_file("word/document.xml", options).unwrap();
        zip.write_all(xml.as_bytes()).unwrap();
        zip.finish().unwrap();
    }
    cursor.into_inner()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_chapter_and_topic_lines_are_placed_on_their_shelves() {
        let bytes = sample_docx(&[
            ("", "Chapter 1: Coordination and Control"),
            ("", "Topic 1: Neuron"),
            ("", "A neuron is a specialized cell that transmits nerve impulses."),
            ("", "Topic: Resting Potential"),
            ("", "The membrane is polarized at rest."),
            ("", "Chapter 2: Support"),
            ("", "Topic: Bones"),
            ("", "Bones support the body."),
        ]);
        let (chapters, warnings) = parse_docx(&bytes).unwrap();
        assert!(warnings.is_empty(), "{warnings:?}");
        assert_eq!(chapters.len(), 2);
        assert_eq!(chapters[0].title, "Chapter 1: Coordination and Control");
        assert_eq!(chapters[0].topics[0].title, "Neuron");
        assert!(chapters[0].topics[0].body.contains("specialized cell"));
        assert_eq!(chapters[0].topics[1].title, "Resting Potential");
        assert_eq!(chapters[1].topics[0].title, "Bones");
    }

    #[test]
    fn heading_styles_and_urdu_labels_are_recognized() {
        let bytes = sample_docx(&[
            ("Heading1", "باب ۱: ہم آہنگی"),
            ("Heading2", "موضوع: نیوران"),
            ("", "نیوران ایک مخصوص خلیہ ہے۔"),
        ]);
        let (chapters, _) = parse_docx(&bytes).unwrap();
        assert_eq!(chapters[0].title, "باب ۱: ہم آہنگی");
        assert_eq!(chapters[0].topics[0].title, "نیوران");
        assert!(chapters[0].topics[0].body.contains("خلیہ"));
    }

    #[test]
    fn import_creates_shelves_and_does_not_replace_saved_notes() {
        let dir = tempfile::tempdir().unwrap();
        let mut db = Database::open(dir.path().join("study.sqlite")).unwrap();
        let student = db.create_profile("Ayesha", "en").unwrap();
        let class_id = db.create_class(&student.id, "Class 10", "").unwrap().id;
        let book_id = db.create_book(&class_id, "Biology", "en").unwrap().id;
        let bytes = sample_docx(&[
            ("", "Chapter 1: Coordination and Control"),
            ("", "Topic: Neuron"),
            ("", "A neuron is a specialized cell that transmits nerve impulses."),
        ]);
        let first = import_word_into_book(&mut db, &book_id, &bytes).unwrap();
        assert_eq!(first.chapters_created, 1);
        assert_eq!(first.topics_created, 1);
        assert_eq!(first.notes_saved, 1);
        let chapter = db.list_chapters(&book_id, false).unwrap();
        assert_eq!(chapter[0].title, "Chapter 1: Coordination and Control");
        let topics = db.list_topics(&chapter[0].id, false).unwrap();
        assert_eq!(topics[0].title, "Neuron");
        assert!(topics[0].has_reference);
        db.save_topic(
            &topics[0].id,
            TopicSaveInput {
                title: "Neuron".into(),
                language: "en".into(),
                reference_text: "Student edited this note.".into(),
                concepts: Vec::new(),
            },
        )
        .unwrap();
        let second = import_word_into_book(&mut db, &book_id, &bytes).unwrap();
        assert_eq!(second.chapters_created, 0);
        assert_eq!(second.topics_created, 0);
        assert_eq!(second.notes_left_unchanged, 1);
        assert_eq!(
            db.get_topic(&topics[0].id).unwrap().reference_text,
            "Student edited this note."
        );
        assert_eq!(db.list_topics(&chapter[0].id, false).unwrap().len(), 1);
    }

    #[test]
    fn bold_headings_become_topics_under_each_chapter() {
        let bytes = docx_runs(&[
            vec![("Class 10 Biology", true)],
            vec![("Chapter 2", true)],
            vec![("Capillaries.", true)],
            vec![("These tiny blood vessels have thin walls.", false)],
            vec![("Venules.", true)],
            vec![("Veins begin as tiny vessels.", false)],
            vec![("calcium.", true)],
            vec![("Mineral ions: dissolved mineral salts.", true)],
            vec![("chlorides,", false)],
            vec![("Red blood cells.", true)],
            vec![
                ("They are called erythrocytes.", true),
                (" A single red blood cell is circular.", false),
            ],
            vec![("One.", true), (" Coronary arteries supply the heart.", false)],
            vec![("Unit 3   Respiratory system:-", true)],
            vec![("Respiration.", true)],
            vec![("Respiration is a process by which cells obtain energy.", false)],
        ]);
        let (chapters, _) = parse_docx(&bytes).unwrap();
        assert!(chapters.iter().all(|chapter| chapter.title != "Imported notes"));
        assert_eq!(chapters[0].title, "Chapter 2");
        let titles: Vec<_> = chapters[0].topics.iter().map(|topic| topic.title.as_str()).collect();
        assert!(titles.contains(&"Capillaries"), "{titles:?}");
        assert!(titles.contains(&"Venules"), "{titles:?}");
        assert!(titles.contains(&"Red blood cells"), "{titles:?}");
        assert!(!titles.iter().any(|title| title.contains("erythrocytes")), "{titles:?}");
        let capillaries = chapters[0].topics.iter().find(|topic| topic.title == "Capillaries").unwrap();
        assert!(capillaries.body.contains("thin walls"));
        assert!(!capillaries.body.contains("tiny vessels"));
        let cells = chapters[0].topics.iter().find(|topic| topic.title == "Red blood cells").unwrap();
        assert!(cells.body.contains("erythrocytes"));
        assert!(cells.body.contains("circular"));
        let minerals = chapters[0].topics.iter().find(|topic| topic.title == "Mineral ions").unwrap();
        assert!(minerals.body.contains("dissolved mineral salts"));
        assert!(minerals.body.contains("chlorides"));
        assert_eq!(chapters[1].title, "Unit 3 Respiratory system");
        assert_eq!(chapters[1].topics[0].title, "Respiration");
        assert!(chapters[1].topics[0].body.contains("obtain energy"));
    }

    #[test]
    fn attached_biology_file_places_bold_topics_when_provided() {
        let Ok(path) = std::env::var("STUDY_RECALL_SAMPLE_DOCX") else {
            return;
        };
        let bytes = std::fs::read(path).unwrap();
        let (chapters, _) = parse_docx(&bytes).unwrap();
        let chapter = chapters.iter().find(|item| item.title.starts_with("Chapter 2")).expect("Chapter 2");
        let capillaries = chapter.topics.iter().find(|topic| topic.title == "Capillaries").expect("Capillaries");
        assert!(capillaries.body.contains("thin walls"));
        assert!(!capillaries.body.contains("venules"));
        let cells = chapter.topics.iter().find(|topic| topic.title == "Red blood cells").expect("Red blood cells");
        assert!(cells.body.contains("erythrocytes"));
        assert!(!chapter.topics.iter().any(|topic| topic.title.contains("erythrocytes")));
        assert!(chapter.topics.iter().any(|topic| topic.title == "Venules"));
        assert!(chapter.topics.iter().any(|topic| topic.title == "Veins"));
        assert!(chapters.iter().any(|item| item.title.contains("Respiratory")));
        assert!(chapters.iter().all(|item| item.title != "Imported notes"));
    }
}
