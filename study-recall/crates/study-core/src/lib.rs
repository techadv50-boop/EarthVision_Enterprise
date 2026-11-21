//! Offline study, recall, and examination engine.
//!
//! Student notes stay in a local SQLite database. The Windows installer includes a local
//! speech program. Descriptive grading calls llama.cpp only when that model is configured.
//! Otherwise the application keeps an explicit, labeled fallback.

pub mod backup;
pub mod db;
pub mod docx_import;
pub mod error;
pub mod exam;
pub mod grading;
pub mod hierarchy;
pub mod oral;
pub mod progress;
pub mod questions;
pub mod speech;
pub mod textutil;

#[cfg(test)]
mod flow_tests;

pub use backup::BackupEntry;
pub use db::{new_id, Database, ModelInfo, Profile, Settings, SettingsUpdate, RECOVERY_POLICY};
pub use docx_import::{import_word_into_book, ImportReport, ImportedChapter};
pub use error::{AppError, AppResult};
pub use exam::{
    render_result_html, ActiveExam, CreateExamRequest, CreatedExam, ExamAnswerInput, ExamResult,
    ExamSync, ExamView, QuestionReview, StoredAnswer,
};
pub use grading::{grade_descriptive, grade_fib, grade_mcq, grade_recall, ConceptRef};
pub use hierarchy::{
    BookSummary, ChapterSummary, ClassSummary, TopicDetail, TopicDraftInput, TopicHit, TopicSaveInput,
    TopicSummary, TrashItem,
};
pub use oral::{OralPrompt, OralStep, OralSummary};
pub use progress::{ProgressDashboard, RevisionTopic};
pub use questions::{build_paper, propose, PaperOffer, Proposal};
pub use speech::{
    apply_bundled_whisper, assess_llama, assess_whisper, decode_audio_allowing_whitespace, transcribe_wav,
    BlockingRunner, SpeechConfig, SpeechOutcome,
};
