mod commands;
mod speak;

use std::path::PathBuf;
use std::sync::Mutex;

use study_core::Database;
use tauri::Manager;

pub struct AppState {
    pub db: Mutex<Database>,
    pub speech_dir: PathBuf,
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            let mut db = Database::open(dir.join("study-recall.sqlite")).map_err(box_err)?;
            if let Ok(resources) = app.path().resource_dir() {
                let _ = study_core::apply_bundled_whisper(&mut db, &resources);
            }
            if let Ok(exe) = std::env::current_exe() {
                if let Some(folder) = exe.parent() {
                    let _ = study_core::apply_bundled_whisper(&mut db, folder);
                }
            }
            let _ = db.refresh_models();
            let speech_dir = dir.join("speech-jobs");
            std::fs::create_dir_all(&speech_dir)?;
            app.manage(AppState {
                db: Mutex::new(db),
                speech_dir,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::bootstrap,
            commands::create_profile,
            commands::update_profile,
            commands::list_profiles,
            commands::get_settings,
            commands::update_settings,
            commands::get_models,
            commands::update_model,
            commands::refresh_models,
            commands::list_classes,
            commands::create_class,
            commands::update_class,
            commands::reorder_classes,
            commands::set_class_archived,
            commands::soft_delete_class,
            commands::restore_class,
            commands::purge_class,
            commands::list_books,
            commands::create_book,
            commands::update_book,
            commands::reorder_books,
            commands::set_book_archived,
            commands::soft_delete_book,
            commands::restore_book,
            commands::purge_book,
            commands::list_chapters,
            commands::create_chapter,
            commands::update_chapter,
            commands::reorder_chapters,
            commands::set_chapter_archived,
            commands::soft_delete_chapter,
            commands::restore_chapter,
            commands::purge_chapter,
            commands::list_topics,
            commands::create_topic,
            commands::update_topic,
            commands::reorder_topics,
            commands::move_topic,
            commands::set_topic_archived,
            commands::soft_delete_topic,
            commands::restore_topic,
            commands::purge_topic,
            commands::search_topics,
            commands::list_trash,
            commands::get_topic,
            commands::save_topic_draft,
            commands::save_topic,
            commands::start_oral,
            commands::start_revision_oral,
            commands::get_oral_prompt,
            commands::submit_oral,
            commands::skip_oral,
            commands::oral_summary,
            commands::propose_exam,
            commands::create_exam,
            commands::start_exam,
            commands::sync_exam,
            commands::save_exam_draft,
            commands::submit_exam_answer,
            commands::resolve_transcription,
            commands::finalize_exam,
            commands::get_exam_result,
            commands::save_exam_html,
            commands::list_active_exams,
            commands::progress,
            commands::revision_topics,
            commands::backup_database,
            commands::restore_database,
            commands::export_json,
            commands::import_json,
            commands::backup_history,
            commands::integrity_check,
            commands::transcribe_audio,
            commands::import_word,
            commands::speak_text
        ])
        .run(tauri::generate_context!())
        .expect("Study Recall failed to start");
}

fn box_err(err: impl std::error::Error + Send + Sync + 'static) -> Box<dyn std::error::Error> {
    Box::new(err)
}
