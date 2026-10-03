import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Minus, Plus } from 'lucide-react';
import { citationApi } from '@/services/api';
import { isFullAdmin, useAuthStore } from '@/store/authStore';

type Wing = 'in_process' | 'published';

interface JournalOption {
  id?: number | null;
  name: string;
  abbreviation?: string;
}

interface ReviewRound {
  round: number;
  sent_date?: string | null;
  received_date?: string | null;
}

interface FieldChange {
  field: string;
  label: string;
  previous: string;
  new: string;
}

interface Modification {
  mod_number: number;
  changed_at: string;
  account: string;
  account_username?: string;
  account_email?: string;
  account_name?: string;
  changes: FieldChange[];
  snapshot?: Partial<AuthorRow> & { review_rounds?: ReviewRound[] };
}

interface AuthorRow {
  id: number;
  wing: Wing;
  journal_id?: number | null;
  journal_name?: string | null;
  journal_title?: string | null;
  ojs_number: string;
  title: string;
  author_names: string;
  author_emails: string;
  email_sent_date?: string | null;
  plagiarism: string;
  orcid_id: string;
  received_date?: string | null;
  review_rounds?: ReviewRound[];
  accepted_date?: string | null;
  galley_sent_date?: string | null;
  galley_received_date?: string | null;
  publish_date?: string | null;
  editorial_status?: string | null;
  soft_reminder_sent?: string | null;
  second_reminder_sent?: string | null;
  last_reminder_sent?: string | null;
  comments?: string | null;
  current_stage?: string | null;
  current_stage_started?: string | null;
  current_stage_days?: number | null;
  current_stage_passed?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;
  original_snapshot?: Partial<AuthorRow> & { review_rounds?: ReviewRound[] };
  modifications?: Modification[];
}

const emptyRound = (round = 1): ReviewRound => ({ round, sent_date: '', received_date: '' });

const COMMENT_MAX = 1000;
const DEFAULT_STAGE_DAYS = 7;

const emptyForm = {
  journal_key: '',
  ojs_number: '',
  title: '',
  author_names: '',
  author_emails: '',
  email_sent_date: '',
  plagiarism: '',
  orcid_id: '',
  received_date: '',
  review_rounds: [emptyRound(1)],
  accepted_date: '',
  galley_sent_date: '',
  galley_received_date: '',
  publish_date: '',
  editorial_status: 'Submission',
  soft_reminder_sent: '',
  second_reminder_sent: '',
  last_reminder_sent: '',
  comments: '',
  current_stage: '',
  current_stage_started: '',
  current_stage_days: DEFAULT_STAGE_DAYS,
  current_stage_passed: false,
};

type FormState = typeof emptyForm;

function roundsFrom(row: AuthorRow): ReviewRound[] {
  const rounds = (row.review_rounds || []).map((item, index) => ({
    round: item.round || index + 1,
    sent_date: item.sent_date || '',
    received_date: item.received_date || '',
  }));
  return rounds.length ? rounds : [emptyRound(1)];
}

function journalLabel(journal: JournalOption) {
  return journal.name || journal.abbreviation || '';
}

function rowJournalKey(row: AuthorRow, journals: JournalOption[]) {
  if (row.journal_id) {
    const match = journals.find((journal) => journal.id === row.journal_id);
    return match ? journalKey(match) : `id:${row.journal_id}`;
  }
  const title = (row.journal_title || row.journal_name || '').trim();
  if (!title) return '';
  const lower = title.toLowerCase();
  const match = journals.find(
    (journal) =>
      (journal.abbreviation || '').toLowerCase() === lower || journal.name.toLowerCase() === lower,
  );
  return match ? journalKey(match) : `name:${title}`;
}

function rowToForm(row: AuthorRow, journals: JournalOption[]) {
  return {
    journal_key: rowJournalKey(row, journals),
    ojs_number: row.ojs_number || '',
    title: row.title || '',
    author_names: row.author_names || '',
    author_emails: row.author_emails || '',
    email_sent_date: row.email_sent_date || '',
    plagiarism: row.plagiarism || '',
    orcid_id: row.orcid_id || '',
    received_date: row.received_date || '',
    review_rounds: roundsFrom(row),
    accepted_date: row.accepted_date || '',
    galley_sent_date: row.galley_sent_date || '',
    galley_received_date: row.galley_received_date || '',
    publish_date: row.publish_date || '',
    editorial_status: row.editorial_status || 'Submission',
    soft_reminder_sent: row.soft_reminder_sent || '',
    second_reminder_sent: row.second_reminder_sent || '',
    last_reminder_sent: row.last_reminder_sent || '',
    comments: row.comments || '',
    current_stage: row.current_stage || '',
    current_stage_started: row.current_stage_started || '',
    current_stage_days: row.current_stage_days || DEFAULT_STAGE_DAYS,
    current_stage_passed: Boolean(row.current_stage_passed),
  };
}

function formatDay(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function journalKey(journal: JournalOption) {
  if (journal.id) return `id:${journal.id}`;
  return `name:${journal.name || journal.abbreviation || ''}`;
}

function parseJournalKey(key: string): { journal_id: number | null; journal_title: string } {
  if (key.startsWith('id:')) {
    const id = Number(key.slice(3));
    return { journal_id: Number.isFinite(id) ? id : null, journal_title: '' };
  }
  if (key.startsWith('name:')) return { journal_id: null, journal_title: key.slice(5) };
  if (key.startsWith('abbr:')) return { journal_id: null, journal_title: key.slice(5) };
  return { journal_id: null, journal_title: key };
}

function applySnapshot(row: AuthorRow, snap?: Partial<AuthorRow> | null): AuthorRow {
  if (!snap || Object.keys(snap).length === 0) return row;
  return {
    ...row,
    journal_id: (snap.journal_id as number | null | undefined) ?? row.journal_id,
    journal_name: snap.journal_name ?? snap.journal_title ?? row.journal_name,
    journal_title: snap.journal_title ?? row.journal_title,
    ojs_number: snap.ojs_number ?? row.ojs_number,
    title: snap.title ?? row.title,
    author_names: snap.author_names ?? row.author_names,
    author_emails: snap.author_emails ?? row.author_emails,
    email_sent_date: snap.email_sent_date ?? row.email_sent_date,
    plagiarism: snap.plagiarism ?? row.plagiarism,
    orcid_id: snap.orcid_id ?? row.orcid_id,
    received_date: snap.received_date ?? row.received_date,
    review_rounds: snap.review_rounds ?? row.review_rounds,
    accepted_date: snap.accepted_date ?? row.accepted_date,
    galley_sent_date: snap.galley_sent_date ?? row.galley_sent_date,
    galley_received_date: snap.galley_received_date ?? row.galley_received_date,
    publish_date: snap.publish_date ?? row.publish_date,
    editorial_status: snap.editorial_status ?? row.editorial_status,
    soft_reminder_sent: snap.soft_reminder_sent ?? row.soft_reminder_sent,
    second_reminder_sent: snap.second_reminder_sent ?? row.second_reminder_sent,
    last_reminder_sent: snap.last_reminder_sent ?? row.last_reminder_sent,
    comments: snap.comments ?? row.comments,
    current_stage: snap.current_stage ?? row.current_stage,
    current_stage_started: snap.current_stage_started ?? row.current_stage_started,
    current_stage_days: snap.current_stage_days ?? row.current_stage_days,
    current_stage_passed: snap.current_stage_passed ?? row.current_stage_passed,
  };
}

const EDITORIAL_STATUSES = [
  'Submission',
  'Waiting for reviewer to be assigned',
  'Request for revisions',
  'Revisions have been submitted',
  'Sent for copy editing',
] as const;

type SlaTone = 'red' | 'green' | 'white';

function parseDay(value?: string | null): Date | null {
  if (!value) return null;
  const text = value.length >= 10 ? value.slice(0, 10) : value;
  const date = new Date(`${text}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function stageKey(round: number, kind: 'sent' | 'received') {
  return `round_${round}_${kind}`;
}

function stageLabel(key?: string | null) {
  const text = (key || '').trim();
  if (!text) return 'None';
  const match = text.match(/^round_(\d+)_(sent|received)$/);
  if (match) {
    return match[2] === 'sent'
      ? `Round ${match[1]} review sent date`
      : `Round ${match[1]} review receive date`;
  }
  if (text === 'accepted_date') return 'Acceptance date';
  if (text === 'galley_sent_date') return 'Galley sent date';
  if (text === 'galley_received_date') return 'Galley received date';
  if (text === 'publish_date') return 'Publish date';
  return text;
}

function stageOptions(rounds: ReviewRound[]) {
  const items = [{ value: '', label: 'None' }];
  const count = Math.max(rounds.length, 1);
  for (let index = 0; index < count; index += 1) {
    items.push({ value: stageKey(index + 1, 'sent'), label: `Round ${index + 1} review sent date` });
    items.push({
      value: stageKey(index + 1, 'received'),
      label: `Round ${index + 1} review receive date`,
    });
  }
  items.push({ value: 'accepted_date', label: 'Acceptance date' });
  items.push({ value: 'galley_sent_date', label: 'Galley sent date' });
  items.push({ value: 'galley_received_date', label: 'Galley received date' });
  items.push({ value: 'publish_date', label: 'Publish date' });
  return items;
}

function dateForStage(data: {
  review_rounds?: ReviewRound[];
  accepted_date?: string | null;
  galley_sent_date?: string | null;
  galley_received_date?: string | null;
  publish_date?: string | null;
}, key: string) {
  const match = key.match(/^round_(\d+)_(sent|received)$/);
  if (match) {
    const round = data.review_rounds?.[Number(match[1]) - 1];
    return (match[2] === 'sent' ? round?.sent_date : round?.received_date) || '';
  }
  if (key === 'accepted_date') return data.accepted_date || '';
  if (key === 'galley_sent_date') return data.galley_sent_date || '';
  if (key === 'galley_received_date') return data.galley_received_date || '';
  if (key === 'publish_date') return data.publish_date || '';
  return '';
}

function currentStageTone(
  stageKeyValue: string,
  data: {
    current_stage?: string | null;
    current_stage_started?: string | null;
    current_stage_days?: number | null;
    current_stage_passed?: boolean | null;
  },
  now = new Date(),
): SlaTone | undefined {
  if (!data.current_stage || data.current_stage !== stageKeyValue) return undefined;
  if (data.current_stage_passed) return 'green';
  const start = parseDay(data.current_stage_started);
  if (!start) return 'white';
  const allowed =
    Number.isFinite(Number(data.current_stage_days)) && Number(data.current_stage_days) > 0
      ? Number(data.current_stage_days)
      : DEFAULT_STAGE_DAYS;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const elapsed = Math.floor((today.getTime() - start.getTime()) / 86400000);
  return elapsed > allowed ? 'red' : 'white';
}

function slaInputClass(tone?: SlaTone) {
  if (tone === 'red') return 'ring-2 ring-red-500';
  if (tone === 'green') return 'ring-2 ring-emerald-400';
  if (tone === 'white') return 'ring-1 ring-white/50';
  return '';
}

function SlaDot({ tone, label }: { tone: SlaTone; label: string }) {
  const color = tone === 'red' ? 'bg-red-500' : tone === 'green' ? 'bg-emerald-400' : 'bg-white';
  const title =
    tone === 'red'
      ? `${label}: current state is overdue and not marked passed`
      : tone === 'green'
        ? `${label}: current state marked passed`
        : `${label}: current state, waiting`;
  return <button type="button" tabIndex={-1} className={`w-3.5 h-3.5 rounded-full shrink-0 ${color}`} title={title} />;
}

function DateSlaField({
  label,
  value,
  onChange,
  tone,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  tone?: SlaTone;
}) {
  return (
    <label className="text-sm text-gray-400">
      <span className="inline-flex items-center gap-2">
        {label}
        {tone ? <SlaDot tone={tone} label={label} /> : null}
      </span>
      <input
        className={`input-field mt-1 ${slaInputClass(tone)}`}
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function recordPath(wing: Wing, id: number) {
  return wing === 'in_process' ? `/authors/in-process/${id}` : `/authors/published/${id}`;
}

function slaTextClass(tone: SlaTone) {
  if (tone === 'red') return 'text-red-400';
  if (tone === 'green') return 'text-emerald-400';
  return 'text-gray-200';
}

function ReportField({
  label,
  value,
  tone,
}: {
  label: string;
  value?: string | null;
  tone?: SlaTone;
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-gray-500 inline-flex items-center gap-2">
        {tone ? <SlaDot tone={tone} label={label} /> : null}
        {label}
      </p>
      <p className={`text-sm break-words ${tone ? slaTextClass(tone) : 'text-gray-200'}`}>
        {value && String(value).trim() ? value : '—'}
      </p>
    </div>
  );
}

type DisplayRow = {
  key: string;
  article: AuthorRow;
  data: AuthorRow;
  label: string;
  dated: string | null;
  isOriginal: boolean;
};

function HistoryCard({ ver }: { ver: DisplayRow }) {
  const data = ver.data;
  const journal = data.journal_name || data.journal_title || '';
  const rounds = data.review_rounds?.length ? data.review_rounds : [emptyRound(1)];
  return (
    <section className="panel p-4 mb-4">
      <div className="mb-4">
        <h3 className={ver.isOriginal ? 'text-gray-100 font-semibold' : 'text-earth-400 font-semibold'}>
          {ver.label}
        </h3>
        <p className="text-xs text-gray-500">{formatDay(ver.dated)}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <ReportField label="OJS number" value={data.ojs_number} />
        <ReportField label="Journal" value={journal} />
        <ReportField label="Status" value={data.editorial_status || 'Submission'} />
        <ReportField label="Title" value={data.title} />
        <ReportField label="Authors" value={data.author_names} />
        <ReportField label="Email addresses of authors" value={data.author_emails} />
        <ReportField label="Email sent date" value={data.email_sent_date} />
        <ReportField label="Plagiarism" value={data.plagiarism} />
        <ReportField label="ORCID ID" value={data.orcid_id} />
        <ReportField label="Receive date" value={data.received_date} />
        {rounds.map((round, index) => (
          <div key={`${ver.key}-r${index}`} className="md:col-span-2 grid gap-4 md:grid-cols-2">
            <ReportField
              label={`Round ${index + 1} review sent date`}
              value={round.sent_date}
              tone={currentStageTone(stageKey(index + 1, 'sent'), data)}
            />
            <ReportField
              label={`Round ${index + 1} review receive date`}
              value={round.received_date}
              tone={currentStageTone(stageKey(index + 1, 'received'), data)}
            />
          </div>
        ))}
        <ReportField
          label="Acceptance date"
          value={data.accepted_date}
          tone={currentStageTone('accepted_date', data)}
        />
        <ReportField
          label="Galley sent date"
          value={data.galley_sent_date}
          tone={currentStageTone('galley_sent_date', data)}
        />
        <ReportField
          label="Galley received date"
          value={data.galley_received_date}
          tone={currentStageTone('galley_received_date', data)}
        />
        <ReportField
          label="Publish date"
          value={data.publish_date}
          tone={currentStageTone('publish_date', data)}
        />
        <ReportField label="Current state" value={stageLabel(data.current_stage)} />
        <ReportField label="Current-state date" value={data.current_stage_started} />
        <ReportField
          label="Days allowed"
          value={data.current_stage ? String(data.current_stage_days || DEFAULT_STAGE_DAYS) : ''}
        />
        <ReportField
          label="Current state passed"
          value={data.current_stage ? (data.current_stage_passed ? 'Yes' : 'No') : ''}
        />
        <ReportField label="Soft reminder sent" value={data.soft_reminder_sent} />
        <ReportField label="Second reminder sent" value={data.second_reminder_sent} />
        <ReportField label="Last reminder sent" value={data.last_reminder_sent} />
        <div className="md:col-span-2">
          <ReportField label="Comments" value={data.comments} />
        </div>
      </div>
    </section>
  );
}

function displayRows(row: AuthorRow): DisplayRow[] {
  const original = applySnapshot(row, row.original_snapshot);
  const out: DisplayRow[] = [
    {
      key: `${row.id}-original`,
      article: row,
      data: original,
      label: 'Original',
      dated: row.created_at || null,
      isOriginal: true,
    },
  ];
  for (const mod of row.modifications || []) {
    if (!mod.snapshot || Object.keys(mod.snapshot).length === 0) continue;
    out.push({
      key: `${row.id}-mod-${mod.mod_number}`,
      article: row,
      data: applySnapshot(row, mod.snapshot),
      label: `Modification ${mod.mod_number}`,
      dated: mod.changed_at,
      isOriginal: false,
    });
  }
  return out;
}

function articlePayload(wing: Wing, form: FormState, journals: JournalOption[]) {
  const selected = journals.find((journal) => journalKey(journal) === form.journal_key);
  const parsed = parseJournalKey(form.journal_key);
  return {
    wing,
    journal_id: parsed.journal_id,
    journal_title: parsed.journal_title || selected?.name || selected?.abbreviation || '',
    ojs_number: form.ojs_number,
    title: form.title,
    author_names: form.author_names,
    author_emails: form.author_emails,
    email_sent_date: form.email_sent_date || null,
    plagiarism: form.plagiarism,
    orcid_id: form.orcid_id,
    received_date: form.received_date || null,
    review_rounds: form.review_rounds.map((round, index) => ({
      round: index + 1,
      sent_date: round.sent_date || null,
      received_date: round.received_date || null,
    })),
    accepted_date: form.accepted_date || null,
    galley_sent_date: form.galley_sent_date || null,
    galley_received_date: form.galley_received_date || null,
    publish_date: form.publish_date || null,
    editorial_status: form.editorial_status,
    soft_reminder_sent: form.soft_reminder_sent || null,
    second_reminder_sent: form.second_reminder_sent || null,
    last_reminder_sent: form.last_reminder_sent || null,
    comments: form.comments.slice(0, COMMENT_MAX),
    current_stage: form.current_stage,
    current_stage_started: form.current_stage ? form.current_stage_started || null : null,
    current_stage_days: form.current_stage_days || DEFAULT_STAGE_DAYS,
    current_stage_passed: Boolean(form.current_stage && form.current_stage_passed),
  };
}

function ArticleFormFields({
  form,
  journals,
  heading,
  extraRoundButton,
  onChange,
}: {
  form: FormState;
  journals: JournalOption[];
  heading: string;
  extraRoundButton?: boolean;
  onChange: (next: FormState | ((prev: FormState) => FormState)) => void;
}) {
  const field = (key: keyof FormState, value: string | number | boolean) => {
    onChange((prev) => ({ ...prev, [key]: value }));
  };
  const setRound = (index: number, key: 'sent_date' | 'received_date', value: string) => {
    onChange((prev) => ({
      ...prev,
      review_rounds: prev.review_rounds.map((round, idx) =>
        idx === index ? { ...round, [key]: value } : round,
      ),
    }));
  };
  const addRound = () => {
    onChange((prev) => ({
      ...prev,
      review_rounds: [...prev.review_rounds, emptyRound(prev.review_rounds.length + 1)],
    }));
  };
  const removeRound = (index: number) => {
    onChange((prev) => {
      const nextRounds =
        prev.review_rounds.length === 1
          ? prev.review_rounds
          : prev.review_rounds
              .filter((_, idx) => idx !== index)
              .map((round, idx) => ({ ...round, round: idx + 1 }));
      let current = prev.current_stage;
      if (current.startsWith('round_')) {
        const match = current.match(/^round_(\d+)_(sent|received)$/);
        if (match && Number(match[1]) > nextRounds.length) current = '';
      }
      return { ...prev, review_rounds: nextRounds, current_stage: current };
    });
  };
  const setCurrentStage = (value: string) => {
    onChange((prev) => {
      const started = value ? prev.current_stage_started || dateForStage(prev, value) : '';
      return {
        ...prev,
        current_stage: value,
        current_stage_started: started,
        current_stage_passed: value ? prev.current_stage_passed : false,
        current_stage_days: prev.current_stage_days || DEFAULT_STAGE_DAYS,
      };
    });
  };
  const commentLen = form.comments.length;
  return (
    <>
      <h3 className="md:col-span-2 text-sm font-medium" id="author-article-form">
        {heading}
      </h3>
      <label className="text-sm text-gray-400">
        Select journal
        <select
          className="input-field mt-1"
          value={form.journal_key}
          onChange={(e) => field('journal_key', e.target.value)}
        >
          <option value="">Select journal</option>
          {journals.map((journal) => (
            <option key={journalKey(journal)} value={journalKey(journal)}>
              {journalLabel(journal)}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm text-gray-400">
        OJS number
        <input
          className="input-field mt-1"
          value={form.ojs_number}
          onChange={(e) => field('ojs_number', e.target.value)}
        />
      </label>
      <label className="text-sm text-gray-400 md:col-span-2">
        Title
        <input className="input-field mt-1" value={form.title} onChange={(e) => field('title', e.target.value)} />
      </label>
      <label className="text-sm text-gray-400">
        Author names
        <textarea
          className="input-field mt-1 min-h-[4.5rem]"
          value={form.author_names}
          onChange={(e) => field('author_names', e.target.value)}
          placeholder="One name per line, or separated by semicolons"
        />
      </label>
      <div className="space-y-3">
        <label className="text-sm text-gray-400 block">
          Email addresses of authors
          <textarea
            className="input-field mt-1 min-h-[4.5rem]"
            value={form.author_emails}
            onChange={(e) => field('author_emails', e.target.value)}
            placeholder="Matching order with author names"
          />
        </label>
        <label className="text-sm text-gray-400 block">
          Email sent date
          <input
            className="input-field mt-1"
            type="date"
            value={form.email_sent_date}
            onChange={(e) => field('email_sent_date', e.target.value)}
          />
        </label>
      </div>
      <label className="text-sm text-gray-400">
        Plagiarism
        <input
          className="input-field mt-1"
          value={form.plagiarism}
          onChange={(e) => field('plagiarism', e.target.value)}
          placeholder="e.g. 11%"
        />
      </label>
      <label className="text-sm text-gray-400">
        ORCID ID
        <input className="input-field mt-1" value={form.orcid_id} onChange={(e) => field('orcid_id', e.target.value)} />
      </label>
      <label className="text-sm text-gray-400">
        Receive date
        <input
          className="input-field mt-1"
          type="date"
          value={form.received_date}
          onChange={(e) => field('received_date', e.target.value)}
        />
      </label>
      <div className="md:col-span-2 border border-gray-800 rounded-md p-3 space-y-3">
        <p className="text-sm font-medium text-gray-200">Current state</p>
        <p className="text-xs text-gray-500">
          Mark the sequential stage that is waiting now. Add a date and the days allowed. The white
          dot on that stage turns red after those days if it is not marked passed.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-gray-400 md:col-span-2">
            Sequential stage
            <select
              className="input-field mt-1"
              value={form.current_stage}
              onChange={(e) => setCurrentStage(e.target.value)}
            >
              {stageOptions(form.review_rounds).map((option) => (
                <option key={option.value || 'none'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-gray-400">
            Current-state date
            <input
              className="input-field mt-1"
              type="date"
              value={form.current_stage_started}
              onChange={(e) => field('current_stage_started', e.target.value)}
              disabled={!form.current_stage}
            />
          </label>
          <label className="text-sm text-gray-400">
            Days allowed
            <input
              className="input-field mt-1"
              type="number"
              min={1}
              max={365}
              value={form.current_stage_days}
              onChange={(e) => field('current_stage_days', Number(e.target.value) || DEFAULT_STAGE_DAYS)}
              disabled={!form.current_stage}
            />
          </label>
          <label className="text-sm text-gray-300 inline-flex items-center gap-2 md:col-span-2">
            <input
              type="checkbox"
              checked={Boolean(form.current_stage && form.current_stage_passed)}
              disabled={!form.current_stage}
              onChange={(e) => field('current_stage_passed', e.target.checked)}
            />
            Marked as passed
          </label>
        </div>
      </div>
      <div className="md:col-span-2 space-y-3">
        {form.review_rounds.map((round, index) => (
          <div key={round.round} className="border border-gray-800 rounded-md p-3 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-200">Round {index + 1}</p>
              <div className="flex items-center gap-1">
                {index === form.review_rounds.length - 1 && (
                  <button
                    type="button"
                    className="text-gray-400 hover:text-white p-1"
                    onClick={addRound}
                    title={`Add round ${form.review_rounds.length + 1}`}
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                )}
                {index > 0 && (
                  <button
                    type="button"
                    className="text-gray-400 hover:text-white p-1"
                    onClick={() => removeRound(index)}
                    title="Remove this round"
                  >
                    <Minus className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <DateSlaField
                label="Review sent date"
                value={round.sent_date || ''}
                onChange={(value) => setRound(index, 'sent_date', value)}
                tone={currentStageTone(stageKey(index + 1, 'sent'), form)}
              />
              <DateSlaField
                label="Review receive date"
                value={round.received_date || ''}
                onChange={(value) => setRound(index, 'received_date', value)}
                tone={currentStageTone(stageKey(index + 1, 'received'), form)}
              />
            </div>
          </div>
        ))}
        {extraRoundButton ? (
          <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={addRound}>
            <Plus className="w-4 h-4" />
            Add round {form.review_rounds.length + 1}
          </button>
        ) : null}
      </div>
      <DateSlaField
        label="Acceptance date"
        value={form.accepted_date}
        onChange={(value) => field('accepted_date', value)}
        tone={currentStageTone('accepted_date', form)}
      />
      <DateSlaField
        label="Galley sent date"
        value={form.galley_sent_date}
        onChange={(value) => field('galley_sent_date', value)}
        tone={currentStageTone('galley_sent_date', form)}
      />
      <DateSlaField
        label="Galley received date"
        value={form.galley_received_date}
        onChange={(value) => field('galley_received_date', value)}
        tone={currentStageTone('galley_received_date', form)}
      />
      <DateSlaField
        label="Publish date"
        value={form.publish_date}
        onChange={(value) => field('publish_date', value)}
        tone={currentStageTone('publish_date', form)}
      />
      <label className="text-sm text-gray-400">
        Soft reminder sent
        <input
          className="input-field mt-1"
          type="date"
          value={form.soft_reminder_sent}
          onChange={(e) => field('soft_reminder_sent', e.target.value)}
        />
      </label>
      <label className="text-sm text-gray-400">
        Second reminder sent
        <input
          className="input-field mt-1"
          type="date"
          value={form.second_reminder_sent}
          onChange={(e) => field('second_reminder_sent', e.target.value)}
        />
      </label>
      <label className="text-sm text-gray-400">
        Last reminder sent
        <input
          className="input-field mt-1"
          type="date"
          value={form.last_reminder_sent}
          onChange={(e) => field('last_reminder_sent', e.target.value)}
        />
      </label>
      <label className="text-sm text-gray-400 md:col-span-2">
        Comments
        <textarea
          className="input-field mt-1 min-h-[6rem]"
          maxLength={COMMENT_MAX}
          value={form.comments}
          onChange={(e) => field('comments', e.target.value.slice(0, COMMENT_MAX))}
          placeholder="About 100 words, up to 1,000 characters"
        />
        <span className={`block text-xs mt-1 ${commentLen >= COMMENT_MAX ? 'text-red-400' : 'text-gray-500'}`}>
          {commentLen} / {COMMENT_MAX} characters
        </span>
      </label>
      <label className="text-sm text-gray-400 md:col-span-2">
        Status
        <select
          className="input-field mt-1"
          value={form.editorial_status}
          onChange={(e) => field('editorial_status', e.target.value)}
        >
          {EDITORIAL_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

export default function AuthorArticlesPage({ wing }: { wing: Wing }) {
  const { articleId } = useParams();
  if (articleId) {
    return <AuthorRecord wing={wing} articleId={Number(articleId)} />;
  }
  return <AuthorList wing={wing} />;
}

function AuthorList({ wing }: { wing: Wing }) {
  const inProcess = wing === 'in_process';
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [rows, setRows] = useState<AuthorRow[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(inProcess);


  const load = async () => {
    const [{ data }, journalsRes] = await Promise.all([
      citationApi.authorArticles.list(wing),
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
    ]);
    setRows(data as AuthorRow[]);
    setJournals((journalsRes.data || []) as JournalOption[]);
  };

  useEffect(() => {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(inProcess);
    setMsg('');
    setError('');
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wing]);

  const payload = () => articlePayload(wing, form, journals);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg('');
    setError('');
    try {
      if (editingId) {
        await citationApi.authorArticles.update(editingId, payload());
        setMsg('Details saved as a new modification row, with the date of this change.');
      } else {
        await citationApi.authorArticles.create(payload());
        setMsg('Article saved.');
      }
      setForm(emptyForm);
      setEditingId(null);
      if (!inProcess) setShowForm(false);
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not save that article.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = async () => {
    const { data } = await citationApi.authorArticles.template();
    const blob = data instanceof Blob ? data : new Blob([data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'author-database-template.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  const importExcel = async (file: File) => {
    setBusy(true);
    setMsg('');
    setError('');
    try {
      const { data } = await citationApi.authorArticles.importFile(file, wing);
      const extra = data.errors?.length ? ` ${data.errors.slice(0, 3).join(' ')}` : '';
      setMsg(
        `Excel import: ${data.created} added, ${data.updated} updated, ${data.skipped} skipped.${extra}`,
      );
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not import that Excel file.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">
        {inProcess ? 'Under process articles' : 'Published articles'}
      </h2>
      <p className="text-gray-400 text-sm mb-4 max-w-4xl">
        {inProcess
          ? 'This list stays quiet: only OJS numbers. Click a number to open that article’s full historical record in a new tab. Users cannot delete records.'
          : 'Published OJS numbers only. Click a number to open the archived original row and every modification in a new tab.'}
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-4">
        {inProcess && !showForm && (
          <button className="btn-primary" type="button" onClick={() => setShowForm(true)}>
            Add article
          </button>
        )}
        {!inProcess && (
          <button className="btn-secondary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Hide form' : 'Add published article'}
          </button>
        )}
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => void downloadTemplate()}>
          Download Excel template
        </button>
        <label className="btn-secondary cursor-pointer">
          Import Excel
          <input
            type="file"
            className="hidden"
            accept=".xlsx,.xlsm,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.currentTarget.value = '';
              if (file) void importExcel(file);
            }}
          />
        </label>
      </div>

      {showForm && (
        <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2" onSubmit={(e) => void save(e)}>
          <ArticleFormFields
            form={form}
            journals={journals}
            heading={editingId ? 'Add details' : inProcess ? 'Save under process article' : 'Save published article'}
            extraRoundButton
            onChange={setForm}
          />
          <div className="md:col-span-2 flex flex-wrap gap-2">
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save article'}
            </button>
            {editingId && (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyForm);
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}

      <div className="panel p-4">
        <h3 className="text-sm font-medium mb-3">OJS numbers</h3>
        {rows.length === 0 ? (
          <p className="text-gray-500 text-sm">
            {inProcess
              ? 'No under process articles yet. Add one or import an Excel file.'
              : 'No published articles yet. Move a finished record from Under process or import Excel.'}
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {rows.map((row) => (
              <a
                key={row.id}
                className="btn-secondary font-medium"
                href={recordPath(wing, row.id)}
                target="_blank"
                rel="noreferrer"
              >
                {row.ojs_number || `No OJS #${row.id}`}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AuthorRecord({ wing, articleId }: { wing: Wing; articleId: number }) {
  const admin = isFullAdmin(useAuthStore((s) => s.user));
  const navigate = useNavigate();
  const inProcess = wing === 'in_process';
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [row, setRow] = useState<AuthorRow | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [askPassword, setAskPassword] = useState(false);
  const [password, setPassword] = useState('');

  const load = async () => {
    const [{ data }, journalsRes] = await Promise.all([
      citationApi.authorArticles.get(articleId),
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
    ]);
    const article = data as AuthorRow;
    setRow(article);
    setJournals((journalsRes.data || []) as JournalOption[]);
    return article;
  };

  useEffect(() => {
    setEditing(false);
    setForm(emptyForm);
    setMsg('');
    setError('');
    setAskPassword(false);
    setPassword('');
    void load().catch(() => setError('Could not load that OJS record.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId, wing]);

  const payload = () => articlePayload(wing, form, journals);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!row) return;
    setBusy(true);
    setMsg('');
    setError('');
    try {
      await citationApi.authorArticles.update(row.id, payload());
      setMsg('Details saved as a new modification row, with the date of this change.');
      setEditing(false);
      setForm(emptyForm);
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not save that article.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const addDetails = async () => {
    const [{ data }, journalsRes] = await Promise.all([
      citationApi.authorArticles.get(articleId),
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
    ]);
    const article = data as AuthorRow;
    const catalog = (journalsRes.data || []) as JournalOption[];
    setRow(article);
    setJournals(catalog);
    setForm(rowToForm(article, catalog));
    setEditing(true);
    setMsg('');
    setError('');
  };

  const move = async (next: Wing) => {
    if (!row) return;
    setBusy(true);
    setError('');
    try {
      await citationApi.authorArticles.update(row.id, { wing: next });
      navigate(recordPath(next, row.id), { replace: true });
      setMsg(next === 'published' ? 'Moved to published articles.' : 'Moved back to under process.');
    } catch {
      setError('Could not move that article.');
    } finally {
      setBusy(false);
    }
  };

  const removeRecord = async () => {
    if (!row) return;
    setBusy(true);
    setError('');
    try {
      await citationApi.authorArticles.remove(row.id, password);
      setAskPassword(false);
      setPassword('');
      setMsg(`Deleted OJS ${row.ojs_number || row.id} and every linked record.`);
      window.setTimeout(() => {
        if (window.opener) window.close();
        else navigate(inProcess ? '/authors/in-process' : '/authors/published');
      }, 600);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not delete that OJS record.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  if (!row) {
    return (
      <div>
        <p className="text-gray-400">{error || 'Loading OJS record…'}</p>
        <Link className="text-earth-400 text-sm" to={inProcess ? '/authors/in-process' : '/authors/published'}>
          Back to OJS numbers
        </Link>
      </div>
    );
  }

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        <Link className="text-earth-400" to={inProcess ? '/authors/in-process' : '/authors/published'}>
          {inProcess ? 'Under process' : 'Published'}
        </Link>
        {' / historical record'}
      </p>
      <h2 className="text-2xl font-semibold mb-1">{row.ojs_number || 'No OJS number'}</h2>
      <p className="text-gray-400 text-sm mb-4 max-w-4xl">
        Original row and every later modification for this OJS number. All fields are shown here.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-4">
        {inProcess && (
          <button className="btn-primary" type="button" disabled={busy} onClick={() => void addDetails()}>
            Add details
          </button>
        )}
        {inProcess ? (
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => void move('published')}>
            Move to published
          </button>
        ) : (
          <button className="btn-secondary" type="button" disabled={busy} onClick={() => void move('in_process')}>
            Back to under process
          </button>
        )}
        {admin && (
          <button
            className="btn-secondary text-red-400"
            type="button"
            disabled={busy}
            onClick={() => {
              setAskPassword(true);
              setPassword('');
              setError('');
            }}
          >
            Delete this OJS record
          </button>
        )}
      </div>

      {askPassword && admin && (
        <div className="panel p-4 mb-4 max-w-lg">
          <p className="text-sm text-gray-200 mb-2">
            Enter the admin password to delete OJS {row.ojs_number || row.id} and every linked
            original and modification record.
          </p>
          <label className="text-sm text-gray-400">
            Password
            <input
              className="input-field mt-1"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2 mt-3">
            <button className="btn-primary" type="button" disabled={busy || !password} onClick={() => void removeRecord()}>
              {busy ? 'Deleting…' : 'Delete'}
            </button>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => {
                setAskPassword(false);
                setPassword('');
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {editing && (
        <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2" onSubmit={(e) => void save(e)}>
          <ArticleFormFields
            form={form}
            journals={journals}
            heading="Add details"
            onChange={setForm}
          />
          <div className="md:col-span-2 flex flex-wrap gap-2">
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save article'}
            </button>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => {
                setEditing(false);
                setForm(emptyForm);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {displayRows(row).map((ver) => (
        <HistoryCard key={ver.key} ver={ver} />
      ))}
    </div>
  );
}
