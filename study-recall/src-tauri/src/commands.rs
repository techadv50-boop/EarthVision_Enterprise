use std::fs;
use std::path::Path;

use serde::Serialize;
use study_core::{
    decode_audio_allowing_whitespace, import_word_into_book, transcribe_wav, ActiveExam, AppResult, BackupEntry, BookSummary,
    ChapterSummary, ClassSummary, CreateExamRequest, CreatedExam, Database, ExamAnswerInput, ExamResult,
    ExamSync, ExamView, ImportReport, ModelInfo, OralPrompt, OralStep, OralSummary, Profile, ProgressDashboard,
    Proposal, RevisionTopic, Settings, SettingsUpdate, SpeechConfig, SpeechOutcome, TopicDetail,
    TopicDraftInput, TopicHit, TopicSaveInput, TopicSummary, TrashItem, BlockingRunner,
};
use tauri::State;

use crate::AppState;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Bootstrap {
    pub settings: Settings,
    pub profiles: Vec<Profile>,
    pub models: Vec<ModelInfo>,
    pub data_directory: String,
    pub recovery_policy: String,
}

fn with_db<T>(state: &AppState, f: impl FnOnce(&mut Database) -> AppResult<T>) -> Result<T, String> {
    let mut db = state.db.lock().unwrap_or_else(|err| err.into_inner());
    f(&mut db).map_err(|err| err.to_string())
}

#[tauri::command]
pub fn bootstrap(state: State<AppState>) -> Result<Bootstrap, String> {
    with_db(&state, |db| {
        Ok(Bootstrap {
            settings: db.get_settings()?,
            profiles: db.list_profiles()?,
            models: db.get_models()?,
            data_directory: db.path().display().to_string(),
            recovery_policy: study_core::RECOVERY_POLICY.to_string(),
        })
    })
}

#[tauri::command]
pub fn create_profile(state: State<AppState>, name: String, language: String) -> Result<Profile, String> {
    with_db(&state, |db| db.create_profile(&name, &language))
}

#[tauri::command]
pub fn update_profile(
    state: State<AppState>,
    id: String,
    name: String,
    language: String,
) -> Result<Profile, String> {
    with_db(&state, |db| db.update_profile(&id, &name, &language))
}

#[tauri::command]
pub fn list_profiles(state: State<AppState>) -> Result<Vec<Profile>, String> {
    with_db(&state, |db| db.list_profiles())
}

#[tauri::command]
pub fn get_settings(state: State<AppState>) -> Result<Settings, String> {
    with_db(&state, |db| db.get_settings())
}

#[tauri::command]
pub fn update_settings(state: State<AppState>, update: SettingsUpdate) -> Result<Settings, String> {
    with_db(&state, |db| db.update_settings(update))
}

#[tauri::command]
pub fn get_models(state: State<AppState>) -> Result<Vec<ModelInfo>, String> {
    with_db(&state, |db| db.get_models())
}

#[tauri::command]
pub fn update_model(
    state: State<AppState>,
    kind: String,
    binary_path: String,
    model_path: String,
) -> Result<ModelInfo, String> {
    with_db(&state, |db| db.update_model(&kind, &binary_path, &model_path))
}

#[tauri::command]
pub fn refresh_models(state: State<AppState>) -> Result<Vec<ModelInfo>, String> {
    with_db(&state, |db| db.refresh_models())
}

#[tauri::command]
pub fn list_classes(
    state: State<AppState>,
    student_id: String,
    include_archived: bool,
) -> Result<Vec<ClassSummary>, String> {
    with_db(&state, |db| db.list_classes(&student_id, include_archived))
}

#[tauri::command]
pub fn create_class(
    state: State<AppState>,
    student_id: String,
    name: String,
    description: String,
) -> Result<ClassSummary, String> {
    with_db(&state, |db| db.create_class(&student_id, &name, &description))
}

#[tauri::command]
pub fn update_class(
    state: State<AppState>,
    id: String,
    name: String,
    description: String,
) -> Result<ClassSummary, String> {
    with_db(&state, |db| db.update_class(&id, &name, &description))
}

#[tauri::command]
pub fn reorder_classes(
    state: State<AppState>,
    student_id: String,
    ordered_ids: Vec<String>,
) -> Result<(), String> {
    with_db(&state, |db| db.reorder_classes(&student_id, &ordered_ids))
}

#[tauri::command]
pub fn set_class_archived(state: State<AppState>, id: String, archived: bool) -> Result<ClassSummary, String> {
    with_db(&state, |db| db.set_class_archived(&id, archived))
}

#[tauri::command]
pub fn soft_delete_class(state: State<AppState>, id: String) -> Result<(), String> {
    with_db(&state, |db| db.soft_delete_class(&id))
}

#[tauri::command]
pub fn restore_class(state: State<AppState>, id: String) -> Result<ClassSummary, String> {
    with_db(&state, |db| db.restore_class(&id))
}

#[tauri::command]
pub fn purge_class(state: State<AppState>, id: String, confirmation: String) -> Result<(), String> {
    with_db(&state, |db| db.purge_class(&id, &confirmation))
}

#[tauri::command]
pub fn list_books(
    state: State<AppState>,
    class_id: String,
    include_archived: bool,
) -> Result<Vec<BookSummary>, String> {
    with_db(&state, |db| db.list_books(&class_id, include_archived))
}

#[tauri::command]
pub fn create_book(
    state: State<AppState>,
    class_id: String,
    title: String,
    language: String,
) -> Result<BookSummary, String> {
    with_db(&state, |db| db.create_book(&class_id, &title, &language))
}

#[tauri::command]
pub fn update_book(
    state: State<AppState>,
    id: String,
    title: String,
    language: String,
) -> Result<BookSummary, String> {
    with_db(&state, |db| db.update_book(&id, &title, &language))
}

#[tauri::command]
pub fn reorder_books(state: State<AppState>, class_id: String, ordered_ids: Vec<String>) -> Result<(), String> {
    with_db(&state, |db| db.reorder_books(&class_id, &ordered_ids))
}

#[tauri::command]
pub fn set_book_archived(state: State<AppState>, id: String, archived: bool) -> Result<BookSummary, String> {
    with_db(&state, |db| db.set_book_archived(&id, archived))
}

#[tauri::command]
pub fn soft_delete_book(state: State<AppState>, id: String) -> Result<(), String> {
    with_db(&state, |db| db.soft_delete_book(&id))
}

#[tauri::command]
pub fn restore_book(state: State<AppState>, id: String) -> Result<BookSummary, String> {
    with_db(&state, |db| db.restore_book(&id))
}

#[tauri::command]
pub fn purge_book(state: State<AppState>, id: String, confirmation: String) -> Result<(), String> {
    with_db(&state, |db| db.purge_book(&id, &confirmation))
}

#[tauri::command]
pub fn list_chapters(
    state: State<AppState>,
    book_id: String,
    include_archived: bool,
) -> Result<Vec<ChapterSummary>, String> {
    with_db(&state, |db| db.list_chapters(&book_id, include_archived))
}

#[tauri::command]
pub fn create_chapter(state: State<AppState>, book_id: String, title: String) -> Result<ChapterSummary, String> {
    with_db(&state, |db| db.create_chapter(&book_id, &title))
}

#[tauri::command]
pub fn update_chapter(state: State<AppState>, id: String, title: String) -> Result<ChapterSummary, String> {
    with_db(&state, |db| db.update_chapter(&id, &title))
}

#[tauri::command]
pub fn reorder_chapters(state: State<AppState>, book_id: String, ordered_ids: Vec<String>) -> Result<(), String> {
    with_db(&state, |db| db.reorder_chapters(&book_id, &ordered_ids))
}

#[tauri::command]
pub fn set_chapter_archived(
    state: State<AppState>,
    id: String,
    archived: bool,
) -> Result<ChapterSummary, String> {
    with_db(&state, |db| db.set_chapter_archived(&id, archived))
}

#[tauri::command]
pub fn soft_delete_chapter(state: State<AppState>, id: String) -> Result<(), String> {
    with_db(&state, |db| db.soft_delete_chapter(&id))
}

#[tauri::command]
pub fn restore_chapter(state: State<AppState>, id: String) -> Result<ChapterSummary, String> {
    with_db(&state, |db| db.restore_chapter(&id))
}

#[tauri::command]
pub fn purge_chapter(state: State<AppState>, id: String, confirmation: String) -> Result<(), String> {
    with_db(&state, |db| db.purge_chapter(&id, &confirmation))
}

#[tauri::command]
pub fn list_topics(
    state: State<AppState>,
    chapter_id: String,
    include_archived: bool,
) -> Result<Vec<TopicSummary>, String> {
    with_db(&state, |db| db.list_topics(&chapter_id, include_archived))
}

#[tauri::command]
pub fn create_topic(
    state: State<AppState>,
    chapter_id: String,
    title: String,
    language: String,
) -> Result<TopicSummary, String> {
    with_db(&state, |db| db.create_topic(&chapter_id, &title, &language))
}

#[tauri::command]
pub fn update_topic(
    state: State<AppState>,
    id: String,
    title: String,
    language: String,
) -> Result<TopicSummary, String> {
    with_db(&state, |db| db.update_topic(&id, &title, &language))
}

#[tauri::command]
pub fn reorder_topics(
    state: State<AppState>,
    chapter_id: String,
    ordered_ids: Vec<String>,
) -> Result<(), String> {
    with_db(&state, |db| db.reorder_topics(&chapter_id, &ordered_ids))
}

#[tauri::command]
pub fn move_topic(
    state: State<AppState>,
    topic_id: String,
    target_chapter_id: String,
) -> Result<TopicSummary, String> {
    with_db(&state, |db| db.move_topic(&topic_id, &target_chapter_id))
}

#[tauri::command]
pub fn set_topic_archived(state: State<AppState>, id: String, archived: bool) -> Result<TopicSummary, String> {
    with_db(&state, |db| db.set_topic_archived(&id, archived))
}

#[tauri::command]
pub fn soft_delete_topic(state: State<AppState>, id: String) -> Result<(), String> {
    with_db(&state, |db| db.soft_delete_topic(&id))
}

#[tauri::command]
pub fn restore_topic(state: State<AppState>, id: String) -> Result<TopicSummary, String> {
    with_db(&state, |db| db.restore_topic(&id))
}

#[tauri::command]
pub fn purge_topic(state: State<AppState>, id: String, confirmation: String) -> Result<(), String> {
    with_db(&state, |db| db.purge_topic(&id, &confirmation))
}

#[tauri::command]
pub fn search_topics(state: State<AppState>, student_id: String, query: String) -> Result<Vec<TopicHit>, String> {
    with_db(&state, |db| db.search_topics(&student_id, &query))
}

#[tauri::command]
pub fn list_trash(state: State<AppState>, student_id: String) -> Result<Vec<TrashItem>, String> {
    with_db(&state, |db| db.list_trash(&student_id))
}

#[tauri::command]
pub fn get_topic(state: State<AppState>, id: String) -> Result<TopicDetail, String> {
    with_db(&state, |db| db.get_topic(&id))
}

#[tauri::command]
pub fn save_topic_draft(state: State<AppState>, id: String, input: TopicDraftInput) -> Result<TopicDetail, String> {
    with_db(&state, |db| db.save_topic_draft(&id, input))
}

#[tauri::command]
pub fn save_topic(state: State<AppState>, id: String, input: TopicSaveInput) -> Result<TopicDetail, String> {
    with_db(&state, |db| db.save_topic(&id, input))
}

#[tauri::command]
pub fn start_oral(
    state: State<AppState>,
    student_id: String,
    chapter_id: String,
) -> Result<OralPrompt, String> {
    with_db(&state, |db| db.start_oral(&student_id, &chapter_id, None))
}

#[tauri::command]
pub fn start_revision_oral(
    state: State<AppState>,
    student_id: String,
    class_id: Option<String>,
) -> Result<OralPrompt, String> {
    with_db(&state, |db| db.start_revision_oral(&student_id, class_id, None))
}

#[tauri::command]
pub fn get_oral_prompt(state: State<AppState>, session_id: String) -> Result<Option<OralPrompt>, String> {
    with_db(&state, |db| db.get_oral_prompt(&session_id))
}

#[tauri::command]
pub fn submit_oral(state: State<AppState>, session_id: String, transcript: String) -> Result<OralStep, String> {
    with_db(&state, |db| db.submit_oral(&session_id, &transcript))
}

#[tauri::command]
pub fn skip_oral(state: State<AppState>, session_id: String) -> Result<OralStep, String> {
    with_db(&state, |db| db.skip_oral(&session_id))
}

#[tauri::command]
pub fn oral_summary(state: State<AppState>, session_id: String) -> Result<OralSummary, String> {
    with_db(&state, |db| db.oral_summary(&session_id))
}

#[tauri::command]
pub fn propose_exam(
    state: State<AppState>,
    student_id: String,
    book_id: String,
    chapter_ids: Vec<String>,
    difficulty: String,
) -> Result<Proposal, String> {
    with_db(&state, |db| db.propose_exam(&student_id, &book_id, &chapter_ids, &difficulty))
}

#[tauri::command]
pub fn create_exam(state: State<AppState>, request: CreateExamRequest) -> Result<CreatedExam, String> {
    with_db(&state, |db| db.create_exam(request))
}

#[tauri::command]
pub fn start_exam(state: State<AppState>, exam_id: String, wall_now_ms: i64) -> Result<ExamView, String> {
    with_db(&state, |db| db.start_exam(&exam_id, wall_now_ms))
}

#[tauri::command]
pub fn sync_exam(state: State<AppState>, exam_id: String, sync: ExamSync) -> Result<ExamView, String> {
    with_db(&state, |db| db.sync_exam(&exam_id, sync))
}

#[tauri::command]
pub fn save_exam_draft(
    state: State<AppState>,
    exam_id: String,
    question_id: String,
    draft_text: String,
    draft_option: Option<String>,
) -> Result<(), String> {
    with_db(&state, |db| {
        db.save_exam_draft(&exam_id, &question_id, &draft_text, draft_option)?;
        Ok(())
    })
}

#[tauri::command]
pub fn submit_exam_answer(
    state: State<AppState>,
    exam_id: String,
    question_id: String,
    input: ExamAnswerInput,
    wall_now_ms: i64,
) -> Result<ExamView, String> {
    with_db(&state, |db| db.submit_exam_answer(&exam_id, &question_id, input, wall_now_ms))
}

#[tauri::command]
pub fn resolve_transcription(
    state: State<AppState>,
    exam_id: String,
    question_id: String,
    transcript: String,
    failed: bool,
) -> Result<ExamView, String> {
    with_db(&state, |db| db.resolve_transcription(&exam_id, &question_id, &transcript, failed))
}

#[tauri::command]
pub fn finalize_exam(state: State<AppState>, exam_id: String) -> Result<ExamResult, String> {
    with_db(&state, |db| db.finalize_exam(&exam_id))
}

#[tauri::command]
pub fn get_exam_result(state: State<AppState>, exam_id: String) -> Result<ExamResult, String> {
    with_db(&state, |db| db.get_exam_result(&exam_id))
}

#[tauri::command]
pub fn save_exam_html(state: State<AppState>, exam_id: String, path: String) -> Result<(), String> {
    let html = with_db(&state, |db| db.exam_html(&exam_id))?;
    let dest = Path::new(&path);
    if let Some(parent) = dest.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|err| format!("Could not create the folder: {err}"))?;
        }
    }
    fs::write(dest, html).map_err(|err| format!("Could not write the result file: {err}"))
}

#[tauri::command]
pub fn list_active_exams(state: State<AppState>, student_id: String) -> Result<Vec<ActiveExam>, String> {
    with_db(&state, |db| db.list_active_exams(&student_id))
}

#[tauri::command]
pub fn progress(state: State<AppState>, student_id: String) -> Result<ProgressDashboard, String> {
    with_db(&state, |db| db.progress(&student_id))
}

#[tauri::command]
pub fn revision_topics(
    state: State<AppState>,
    student_id: String,
    class_id: Option<String>,
) -> Result<Vec<RevisionTopic>, String> {
    with_db(&state, |db| db.revision_topics(&student_id, class_id.as_deref()))
}

#[tauri::command]
pub fn backup_database(state: State<AppState>, path: String) -> Result<(), String> {
    with_db(&state, |db| db.backup_to(Path::new(&path)))
}

#[tauri::command]
pub fn restore_database(state: State<AppState>, path: String) -> Result<(), String> {
    with_db(&state, |db| db.restore_from(Path::new(&path)))
}

#[tauri::command]
pub fn export_json(state: State<AppState>, path: String) -> Result<(), String> {
    let json = with_db(&state, |db| db.export_json())?;
    fs::write(&path, json).map_err(|err| format!("Could not write the export: {err}"))
}

#[tauri::command]
pub fn import_json(state: State<AppState>, path: String) -> Result<usize, String> {
    let raw = fs::read_to_string(&path).map_err(|err| format!("Could not read the import file: {err}"))?;
    with_db(&state, |db| db.import_json(&raw))
}

#[tauri::command]
pub fn backup_history(state: State<AppState>) -> Result<Vec<BackupEntry>, String> {
    with_db(&state, |db| db.backup_history())
}

#[tauri::command]
pub fn integrity_check(state: State<AppState>) -> Result<String, String> {
    with_db(&state, |db| db.integrity_check())
}

#[tauri::command]
pub async fn transcribe_audio(
    state: State<'_, AppState>,
    audio_base64: String,
    language: String,
) -> Result<SpeechOutcome, String> {
    let (config, retain, parent) = with_db(&state, |db| {
        let models = db.get_models()?;
        let whisper = models
            .into_iter()
            .find(|model| model.kind == "whisper")
            .ok_or_else(|| study_core::AppError::Invalid("Whisper settings are missing.".into()))?;
        let settings = db.get_settings()?;
        Ok((
            SpeechConfig {
                binary_path: whisper.binary_path,
                model_path: whisper.model_path,
            },
            settings.retain_audio,
            state.speech_dir.clone(),
        ))
    })?;
    let bytes = match decode_audio_allowing_whitespace(&audio_base64) {
        Ok(bytes) => bytes,
        Err(err) => return Ok(failed_audio(err)),
    };
    if bytes.len() > 40 * 1024 * 1024 {
        return Ok(failed_audio(
            "The recording is larger than 40 MB. Record the topic in shorter segments and combine the transcripts.".into(),
        ));
    }
    let job = parent.join(study_core::new_id());
    let cleanup = job.clone();
    let outcome = tauri::async_runtime::spawn_blocking(move || {
        transcribe_wav(&BlockingRunner, &config, &bytes, &language, &job, retain)
    })
    .await
    .map_err(|err| format!("Transcription stopped unexpectedly: {err}"))?;
    if outcome.retained_path.is_empty() {
        let _ = fs::remove_dir_all(&cleanup);
    }
    Ok(outcome)
}

#[tauri::command]
pub fn import_word(state: State<AppState>, book_id: String, path: String) -> Result<ImportReport, String> {
    let file = Path::new(&path);
    let extension = file.extension().and_then(|item| item.to_str()).unwrap_or("").to_ascii_lowercase();
    if extension != "docx" {
        return Err("Choose a Word .docx file. Older .doc files need to be saved as .docx first.".into());
    }
    let meta = fs::metadata(file).map_err(|_| "That Word file could not be opened.".to_string())?;
    if meta.len() > 20 * 1024 * 1024 {
        return Err("That Word file is larger than 20 MB. Split it and import each part.".into());
    }
    let bytes = fs::read(file).map_err(|_| "That Word file could not be read.".to_string())?;
    with_db(&state, |db| import_word_into_book(db, &book_id, &bytes))
}

#[tauri::command]
pub async fn speak_text(text: String, language: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || crate::speak::speak_text(&text, &language))
        .await
        .map_err(|err| format!("Reading aloud stopped unexpectedly: {err}"))?
}

fn failed_audio(message: String) -> SpeechOutcome {
    SpeechOutcome {
        ok: false,
        text: String::new(),
        method: String::new(),
        language: String::new(),
        warning: String::new(),
        error_code: "invalid_audio".into(),
        error_message: message,
        retained_path: String::new(),
    }
}
