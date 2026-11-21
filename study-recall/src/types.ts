export type Profile = {
  id: string;
  displayName: string;
  preferredLanguage: string;
  createdAt: string;
  updatedAt: string;
};

export type Settings = {
  theme: string;
  mcqSeconds: number;
  fibSeconds: number;
  shortSeconds: number;
  longSeconds: number;
  wellRememberedPercent: number;
  developingPercent: number;
  activeStudentId: string;
  retainAudio: boolean;
};

export type SettingsUpdate = Partial<Settings>;

export type ModelInfo = {
  kind: string;
  binaryPath: string;
  modelPath: string;
  available: boolean;
  statusMessage: string;
};

export type Bootstrap = {
  settings: Settings;
  profiles: Profile[];
  models: ModelInfo[];
  dataDirectory: string;
  recoveryPolicy: string;
};

export type ClassSummary = {
  id: string;
  name: string;
  description: string;
  sortOrder: number;
  archived: boolean;
  bookCount: number;
  topicCount: number;
  studiedTopicCount: number;
  testedTopicCount: number;
};

export type BookSummary = {
  id: string;
  classId: string;
  title: string;
  language: string;
  sortOrder: number;
  archived: boolean;
  chapterCount: number;
  topicCount: number;
};

export type ChapterSummary = {
  id: string;
  bookId: string;
  title: string;
  sortOrder: number;
  archived: boolean;
  topicCount: number;
  studiedTopicCount: number;
  testedTopicCount: number;
};

export type TopicSummary = {
  id: string;
  chapterId: string;
  title: string;
  language: string;
  sortOrder: number;
  archived: boolean;
  hasReference: boolean;
  revisionStatus: string;
  lastScore: number | null;
};

export type TopicHit = {
  topicId: string;
  title: string;
  language: string;
  classId: string;
  className: string;
  bookId: string;
  bookTitle: string;
  chapterId: string;
  chapterTitle: string;
  hasReference: boolean;
  revisionStatus: string;
};

export type TrashItem = {
  kind: string;
  id: string;
  name: string;
  deletedAt: string;
  parentLabel: string;
};

export type Concept = {
  kind: string;
  label: string;
  content: string;
  aliases: string;
};

export type TopicDetail = {
  id: string;
  title: string;
  language: string;
  textDirection: string;
  classId: string;
  className: string;
  bookId: string;
  bookTitle: string;
  chapterId: string;
  chapterTitle: string;
  referenceText: string;
  draftText: string;
  hasDraft: boolean;
  concepts: Concept[];
  draftConcepts: Concept[];
  revisionStatus: string;
  lastScore: number | null;
};

export type SpeechOutcome = {
  ok: boolean;
  text: string;
  method: string;
  language: string;
  warning: string;
  errorCode: string;
  errorMessage: string;
  retainedPath: string;
};

export type OralPrompt = {
  sessionId: string;
  position: number;
  total: number;
  topicId: string;
  topicTitle: string;
  className: string;
  bookTitle: string;
  chapterTitle: string;
  language: string;
  textDirection: string;
};

export type OralTopicResult = {
  topicId: string;
  title: string;
  skipped: boolean;
  transcript: string;
  referenceText: string;
  essentialCoverage: number | null;
  factualCorrectness: number | null;
  supportingDetail: number | null;
  overall: number | null;
  method: string;
  confidence: string;
  covered: string[];
  missing: string[];
  incorrect: string[];
  revision: string;
  category: string;
  reasons: string[];
};

export type OralSummary = {
  sessionId: string;
  status: string;
  attempted: number;
  skipped: number;
  averagePercent: number | null;
  successful: number;
  partial: number;
  needsRevision: number;
  wellRememberedPercent: number;
  developingPercent: number;
  topics: OralTopicResult[];
};

export type OralStep = {
  finished: boolean;
  result: OralTopicResult;
  summary: OralSummary | null;
};

export type PaperOffer = {
  sizeId: string;
  title: string;
  feasible: boolean;
  reason: string;
  fibCount: number;
  mcqCount: number;
  shortCount: number;
  longCount: number;
  totalMarks: number;
  sectionAMarks: number;
  sectionBMarks: number;
  sectionCMarks: number;
  percentA: number;
  percentB: number;
  percentC: number;
  roundingNote: string;
};

export type Proposal = {
  offers: PaperOffer[];
  fibAvailable: number;
  mcqAvailable: number;
  shortAvailable: number;
  longAvailable: number;
  difficultyNote: string;
  materialNote: string;
};

export type CreatedExam = {
  examId: string;
  instructions: string;
  offer: PaperOffer;
  questionCount: number;
  recoveryPolicy: string;
  className: string;
  bookTitle: string;
  chapterTitles: string[];
};

export type McqOption = { id: string; text: string };

export type ExamQuestionView = {
  id: string;
  position: number;
  questionType: string;
  prompt: string;
  options: McqOption[];
  maxMarks: number;
  draftText: string;
  draftOption: string | null;
  locked: boolean;
  durationMs: number;
};

export type ExamView = {
  examId: string;
  status: string;
  currentIndex: number;
  totalQuestions: number;
  question: ExamQuestionView | null;
  remainingMs: number;
  durationMs: number;
  timerGeneration: number;
  startedWallMs: number | null;
  progress: number;
  pendingTranscription: number;
  recoveryPolicy: string;
  totalMarks: number;
  weightingNote: string;
  instructions: string;
  className: string;
  bookTitle: string;
};

export type QuestionReview = {
  position: number;
  questionType: string;
  prompt: string;
  options: McqOption[];
  studentAnswer: string;
  correctAnswer: string;
  awarded: number | null;
  maxMarks: number;
  explanation: string;
  sourceTopicId: string;
  topicTitle: string;
  confidence: string;
  method: string;
  covered: string[];
  missing: string[];
  incorrect: string[];
};

export type SectionScore = {
  name: string;
  awarded: number;
  maxMarks: number;
  correct: number;
  partial: number;
  incorrect: number;
  unanswered: number;
  review: number;
};

export type ExamResult = {
  examId: string;
  studentName: string;
  className: string;
  bookTitle: string;
  chapterTitles: string[];
  takenAt: string;
  obtainedMarks: number;
  maxMarks: number;
  percentage: number;
  timeTakenMs: number;
  correctCount: number;
  partialCount: number;
  incorrectCount: number;
  unansweredCount: number;
  reviewCount: number;
  sections: SectionScore[];
  questions: QuestionReview[];
  weightingNote: string;
  gradingNote: string;
};

export type ActiveExam = {
  examId: string;
  status: string;
  className: string;
  bookTitle: string;
  createdAt: string;
  questionCount: number;
  currentIndex: number;
};

export type GroupScore = {
  id: string;
  label: string;
  parentLabel: string;
  averagePercent: number | null;
  attempts: number;
};

export type ProgressDashboard = {
  testsCompleted: number;
  oralSessions: number;
  writtenExams: number;
  averageOral: number | null;
  averageWritten: number | null;
  byClass: GroupScore[];
  byBook: GroupScore[];
  byChapter: GroupScore[];
  byTopic: GroupScore[];
  missedConcepts: { concept: string; count: number }[];
  needsRevision: number;
  developing: number;
  wellRemembered: number;
  untested: number;
  revisionCompleted: number;
  recentWritten: { id: string; label: string; percentage: number; kind: string }[];
  recentOral: { id: string; label: string; percentage: number; kind: string }[];
  wellRememberedPercent: number;
  developingPercent: number;
};

export type RevisionTopic = {
  topicId: string;
  title: string;
  className: string;
  bookTitle: string;
  chapterTitle: string;
  status: string;
  lastScore: number | null;
  lastSource: string;
};

export type ImportedTopic = {
  title: string;
  body: string;
};

export type ImportedChapter = {
  title: string;
  topics: ImportedTopic[];
};

export type ImportReport = {
  chaptersCreated: number;
  chaptersReused: number;
  topicsCreated: number;
  notesSaved: number;
  notesLeftUnchanged: number;
  warnings: string[];
  chapters: ImportedChapter[];
};

export type BackupEntry = {
  id: string;
  path: string;
  action: string;
  status: string;
  message: string;
  createdAt: string;
};
