import { invoke } from "@tauri-apps/api/core";
import type {
  ActiveExam,
  BackupEntry,
  BookSummary,
  Bootstrap,
  ChapterSummary,
  ClassSummary,
  Concept,
  CreatedExam,
  ExamResult,
  ExamView,
  ModelInfo,
  OralPrompt,
  OralStep,
  OralSummary,
  Profile,
  ProgressDashboard,
  Proposal,
  RevisionTopic,
  Settings,
  SettingsUpdate,
  ImportReport,
  SpeechOutcome,
  TopicDetail,
  TopicHit,
  TopicSummary,
  TrashItem,
} from "./types";

export function errorText(err: unknown): string {
  if (typeof err === "string" && err.trim()) return err;
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Saved study material was not removed.";
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch (err) {
    throw new Error(errorText(err));
  }
}

export const api = {
  bootstrap: () => call<Bootstrap>("bootstrap"),
  createProfile: (name: string, language: string) => call<Profile>("create_profile", { name, language }),
  updateProfile: (id: string, name: string, language: string) =>
    call<Profile>("update_profile", { id, name, language }),
  getSettings: () => call<Settings>("get_settings"),
  updateSettings: (update: SettingsUpdate) => call<Settings>("update_settings", { update }),
  getModels: () => call<ModelInfo[]>("get_models"),
  updateModel: (kind: string, binaryPath: string, modelPath: string) =>
    call<ModelInfo>("update_model", { kind, binaryPath, modelPath }),
  refreshModels: () => call<ModelInfo[]>("refresh_models"),
  listClasses: (studentId: string, includeArchived = false) =>
    call<ClassSummary[]>("list_classes", { studentId, includeArchived }),
  createClass: (studentId: string, name: string, description: string) =>
    call<ClassSummary>("create_class", { studentId, name, description }),
  updateClass: (id: string, name: string, description: string) =>
    call<ClassSummary>("update_class", { id, name, description }),
  reorderClasses: (studentId: string, orderedIds: string[]) =>
    call<void>("reorder_classes", { studentId, orderedIds }),
  setClassArchived: (id: string, archived: boolean) => call<ClassSummary>("set_class_archived", { id, archived }),
  softDeleteClass: (id: string) => call<void>("soft_delete_class", { id }),
  restoreClass: (id: string) => call<ClassSummary>("restore_class", { id }),
  purgeClass: (id: string, confirmation: string) => call<void>("purge_class", { id, confirmation }),
  listBooks: (classId: string, includeArchived = false) =>
    call<BookSummary[]>("list_books", { classId, includeArchived }),
  createBook: (classId: string, title: string, language: string) =>
    call<BookSummary>("create_book", { classId, title, language }),
  updateBook: (id: string, title: string, language: string) =>
    call<BookSummary>("update_book", { id, title, language }),
  reorderBooks: (classId: string, orderedIds: string[]) => call<void>("reorder_books", { classId, orderedIds }),
  setBookArchived: (id: string, archived: boolean) => call<BookSummary>("set_book_archived", { id, archived }),
  softDeleteBook: (id: string) => call<void>("soft_delete_book", { id }),
  restoreBook: (id: string) => call<BookSummary>("restore_book", { id }),
  purgeBook: (id: string, confirmation: string) => call<void>("purge_book", { id, confirmation }),
  listChapters: (bookId: string, includeArchived = false) =>
    call<ChapterSummary[]>("list_chapters", { bookId, includeArchived }),
  createChapter: (bookId: string, title: string) => call<ChapterSummary>("create_chapter", { bookId, title }),
  updateChapter: (id: string, title: string) => call<ChapterSummary>("update_chapter", { id, title }),
  reorderChapters: (bookId: string, orderedIds: string[]) =>
    call<void>("reorder_chapters", { bookId, orderedIds }),
  setChapterArchived: (id: string, archived: boolean) =>
    call<ChapterSummary>("set_chapter_archived", { id, archived }),
  softDeleteChapter: (id: string) => call<void>("soft_delete_chapter", { id }),
  restoreChapter: (id: string) => call<ChapterSummary>("restore_chapter", { id }),
  purgeChapter: (id: string, confirmation: string) => call<void>("purge_chapter", { id, confirmation }),
  listTopics: (chapterId: string, includeArchived = false) =>
    call<TopicSummary[]>("list_topics", { chapterId, includeArchived }),
  createTopic: (chapterId: string, title: string, language: string) =>
    call<TopicSummary>("create_topic", { chapterId, title, language }),
  updateTopic: (id: string, title: string, language: string) =>
    call<TopicSummary>("update_topic", { id, title, language }),
  reorderTopics: (chapterId: string, orderedIds: string[]) =>
    call<void>("reorder_topics", { chapterId, orderedIds }),
  moveTopic: (topicId: string, targetChapterId: string) =>
    call<TopicSummary>("move_topic", { topicId, targetChapterId }),
  setTopicArchived: (id: string, archived: boolean) => call<TopicSummary>("set_topic_archived", { id, archived }),
  softDeleteTopic: (id: string) => call<void>("soft_delete_topic", { id }),
  restoreTopic: (id: string) => call<TopicSummary>("restore_topic", { id }),
  purgeTopic: (id: string, confirmation: string) => call<void>("purge_topic", { id, confirmation }),
  searchTopics: (studentId: string, query: string) => call<TopicHit[]>("search_topics", { studentId, query }),
  listTrash: (studentId: string) => call<TrashItem[]>("list_trash", { studentId }),
  getTopic: (id: string) => call<TopicDetail>("get_topic", { id }),
  saveTopicDraft: (id: string, title: string, language: string, draftText: string, concepts: Concept[]) =>
    call<TopicDetail>("save_topic_draft", { id, input: { title, language, draftText, concepts } }),
  saveTopic: (id: string, title: string, language: string, referenceText: string, concepts: Concept[]) =>
    call<TopicDetail>("save_topic", { id, input: { title, language, referenceText, concepts } }),
  transcribe: (audioBase64: string, language: string) =>
    call<SpeechOutcome>("transcribe_audio", { audioBase64, language }),
  startOral: (studentId: string, chapterId: string) =>
    call<OralPrompt>("start_oral", { studentId, chapterId }),
  startRevisionOral: (studentId: string, classId?: string) =>
    call<OralPrompt>("start_revision_oral", { studentId, classId: classId ?? null }),
  getOralPrompt: (sessionId: string) => call<OralPrompt | null>("get_oral_prompt", { sessionId }),
  submitOral: (sessionId: string, transcript: string) => call<OralStep>("submit_oral", { sessionId, transcript }),
  skipOral: (sessionId: string) => call<OralStep>("skip_oral", { sessionId }),
  oralSummary: (sessionId: string) => call<OralSummary>("oral_summary", { sessionId }),
  proposeExam: (studentId: string, bookId: string, chapterIds: string[], difficulty: string) =>
    call<Proposal>("propose_exam", { studentId, bookId, chapterIds, difficulty }),
  createExam: (studentId: string, bookId: string, chapterIds: string[], difficulty: string, sizeId: string) =>
    call<CreatedExam>("create_exam", { request: { studentId, bookId, chapterIds, difficulty, sizeId, seed: null } }),
  startExam: (examId: string, wallNowMs: number) => call<ExamView>("start_exam", { examId, wallNowMs }),
  syncExam: (examId: string, wallNowMs: number, timerGeneration?: number, monotonicElapsedMs?: number) =>
    call<ExamView>("sync_exam", {
      examId,
      sync: {
        wallNowMs,
        timerGeneration: timerGeneration ?? null,
        monotonicElapsedMs: monotonicElapsedMs ?? null,
      },
    }),
  saveExamDraft: (examId: string, questionId: string, draftText: string, draftOption: string | null) =>
    call<void>("save_exam_draft", { examId, questionId, draftText, draftOption }),
  submitExamAnswer: (
    examId: string,
    questionId: string,
    responseText: string,
    selectedOption: string | null,
    pendingTranscription: boolean,
    wallNowMs: number,
  ) =>
    call<ExamView>("submit_exam_answer", {
      examId,
      questionId,
      input: { responseText, selectedOption, pendingTranscription },
      wallNowMs,
    }),
  resolveTranscription: (examId: string, questionId: string, transcript: string, failed: boolean) =>
    call<ExamView>("resolve_transcription", { examId, questionId, transcript, failed }),
  finalizeExam: (examId: string) => call<ExamResult>("finalize_exam", { examId }),
  getExamResult: (examId: string) => call<ExamResult>("get_exam_result", { examId }),
  saveExamHtml: (examId: string, path: string) => call<void>("save_exam_html", { examId, path }),
  listActiveExams: (studentId: string) => call<ActiveExam[]>("list_active_exams", { studentId }),
  progress: (studentId: string) => call<ProgressDashboard>("progress", { studentId }),
  revisionTopics: (studentId: string, classId?: string) =>
    call<RevisionTopic[]>("revision_topics", { studentId, classId: classId ?? null }),
  backupDatabase: (path: string) => call<void>("backup_database", { path }),
  restoreDatabase: (path: string) => call<void>("restore_database", { path }),
  exportJson: (path: string) => call<void>("export_json", { path }),
  importJson: (path: string) => call<number>("import_json", { path }),
  backupHistory: () => call<BackupEntry[]>("backup_history"),
  integrityCheck: () => call<string>("integrity_check"),
  importWord: (bookId: string, path: string) => call<ImportReport>("import_word", { bookId, path }),
  speak: (text: string, language: string) => call<string>("speak_text", { text, language }),
};

export async function pickFile(filters?: { name: string; extensions: string[] }[]): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({ multiple: false, directory: false, filters });
  return typeof selected === "string" ? selected : null;
}

export async function pickSavePath(defaultPath: string, filters?: { name: string; extensions: string[] }[]): Promise<string | null> {
  const { save } = await import("@tauri-apps/plugin-dialog");
  const selected = await save({ defaultPath, filters });
  return selected ?? null;
}
