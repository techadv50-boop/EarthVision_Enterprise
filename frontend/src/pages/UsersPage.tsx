import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { adminApi, citationApi } from '@/services/api';
import {
  AUTHOR_WINGS,
  REVIEW_BRANCHES,
  SERVICES,
  emptyPrivileges,
  fullPrivileges,
  useAuthStore,
  type ServicePrivileges,
} from '@/store/authStore';

interface AdminUser {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  desks?: string[];
  privileges?: ServicePrivileges;
  can_manage_users?: boolean;
  access_status?: string;
  assigned_journal_ids?: number[];
}

interface JournalOption {
  id: number;
  name: string;
  abbreviation?: string;
}

function isOperator(user: AdminUser): boolean {
  return Boolean(user.is_superuser || (user.roles || []).includes('admin'));
}

function privilegesOf(user: AdminUser): ServicePrivileges {
  if (isOperator(user)) return fullPrivileges();
  if (user.privileges) {
    return {
      services: user.privileges.services || [],
      review_branches: user.privileges.review_branches || [],
      author_wings: user.privileges.author_wings || [],
      all_journals: Boolean(user.privileges.all_journals),
    };
  }
  return emptyPrivileges();
}

function statusOf(user: AdminUser): 'pending' | 'approved' | 'restricted' {
  const value = (user.access_status || (user.is_active ? 'approved' : 'restricted')).toLowerCase();
  if (value === 'pending' || value === 'restricted') return value;
  return 'approved';
}

function statusLabel(status: string) {
  if (status === 'pending') return 'Pending approval';
  if (status === 'restricted') return 'Restricted';
  return 'Approved';
}

function PrivilegeChecks({
  value,
  journals,
  journalIds,
  disabled,
  onChange,
  onJournals,
}: {
  value: ServicePrivileges;
  journals: JournalOption[];
  journalIds: number[];
  disabled?: boolean;
  onChange: (next: ServicePrivileges) => void;
  onJournals: (ids: number[]) => void;
}) {
  const has = (service: string) => value.services.includes(service);
  const toggleService = (service: string, on: boolean) => {
    const services = new Set(value.services);
    if (on) services.add(service);
    else services.delete(service);
    const next: ServicePrivileges = {
      ...value,
      services: SERVICES.map((s) => s.id).filter((id) => services.has(id)),
    };
    if (!next.services.includes('citation')) next.all_journals = false;
    if (on && service === 'review' && next.review_branches.length === 0) {
      next.review_branches = REVIEW_BRANCHES.map((b) => b.id);
    }
    if (!next.services.includes('review')) next.review_branches = [];
    if (on && service === 'authors' && next.author_wings.length === 0) {
      next.author_wings = AUTHOR_WINGS.map((w) => w.id);
    }
    if (!next.services.includes('authors')) next.author_wings = [];
    onChange(next);
  };
  const toggleList = (key: 'review_branches' | 'author_wings', id: string, on: boolean) => {
    const set = new Set(value[key]);
    if (on) set.add(id);
    else set.delete(id);
    onChange({ ...value, [key]: [...set] });
  };

  return (
    <div className="space-y-3 min-w-[16rem]">
      {SERVICES.map((service) => (
        <div key={service.id} className="space-y-2">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={has(service.id)}
              disabled={disabled}
              onChange={(e) => toggleService(service.id, e.target.checked)}
            />
            <span>
              {service.label}
              <span className="block text-xs text-gray-500 font-normal">{service.hint}</span>
            </span>
          </label>
          {service.id === 'citation' && has('citation') && (
            <div className="ml-6 space-y-2 border-l border-gray-800 pl-3">
              <p className="text-xs text-gray-400">Journals that stay active for this user</p>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={value.all_journals}
                  disabled={disabled}
                  onChange={(e) => onChange({ ...value, all_journals: e.target.checked })}
                />
                All journals
              </label>
              {!value.all_journals &&
                (journals.length === 0 ? (
                  <p className="text-xs text-gray-500">Add a journal first, then tick which ones stay active.</p>
                ) : (
                  journals.map((journal) => (
                    <label key={journal.id} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={journalIds.includes(journal.id)}
                        disabled={disabled}
                        onChange={(e) => {
                          const next = new Set(journalIds);
                          if (e.target.checked) next.add(journal.id);
                          else next.delete(journal.id);
                          onJournals([...next]);
                        }}
                      />
                      {journal.abbreviation || journal.name}
                    </label>
                  ))
                ))}
            </div>
          )}
          {service.id === 'review' && has('review') && (
            <div className="ml-6 space-y-2 border-l border-gray-800 pl-3">
              <p className="text-xs text-gray-400">Article-review branches</p>
              {REVIEW_BRANCHES.map((branch) => (
                <label key={branch.id} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={value.review_branches.includes(branch.id)}
                    disabled={disabled}
                    onChange={(e) => toggleList('review_branches', branch.id, e.target.checked)}
                  />
                  {branch.label}
                </label>
              ))}
            </div>
          )}
          {service.id === 'authors' && has('authors') && (
            <div className="ml-6 space-y-2 border-l border-gray-800 pl-3">
              <p className="text-xs text-gray-400">Author-database wings</p>
              {AUTHOR_WINGS.map((wing) => (
                <label key={wing.id} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={value.author_wings.includes(wing.id)}
                    disabled={disabled}
                    onChange={(e) => toggleList('author_wings', wing.id, e.target.checked)}
                  />
                  {wing.label}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function UsersPage() {
  const current = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [privDraft, setPrivDraft] = useState<Record<number, ServicePrivileges>>({});
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [createPriv, setCreatePriv] = useState<ServicePrivileges>(emptyPrivileges());
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [journalDraft, setJournalDraft] = useState<Record<number, number[]>>({});
  const [createJournalIds, setCreateJournalIds] = useState<number[]>([]);
  const [authorJournals, setAuthorJournals] = useState<{ id?: number | null; name: string; abbreviation?: string }[]>([]);
  const [newJournalName, setNewJournalName] = useState('');
  const [showNewJournal, setShowNewJournal] = useState(false);

  const load = async () => {
    try {
      const [{ data }, journalsRes, authorJournalsRes] = await Promise.all([
        adminApi.users(),
        citationApi.journals.list().catch(() => ({ data: [] as JournalOption[] })),
        citationApi.authorArticles.journals().catch(() => ({ data: [] as { name: string }[] })),
      ]);
      const rows = data as AdminUser[];
      setUsers(rows);
      setPrivDraft(Object.fromEntries(rows.map((row) => [row.id, privilegesOf(row)])));
      setJournalDraft(
        Object.fromEntries(rows.map((row) => [row.id, row.assigned_journal_ids || []])),
      );
      setJournals((journalsRes.data || []) as JournalOption[]);
      setAuthorJournals(
        ((authorJournalsRes.data || []) as { id?: number | null; name: string; abbreviation?: string }[]).filter(
          (journal) => !journal.id,
        ),
      );
    } catch {
      setError('Could not load the user list. You can still add a user below.');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const savePrivileges = async (
    user: AdminUser,
    extras: Record<string, unknown> = {},
    success = `Saved privileges for ${user.username}.`,
  ) => {
    setBusy(user.id);
    setMsg('');
    setError('');
    try {
      const privileges = privDraft[user.id] || emptyPrivileges();
      await adminApi.updateUser(user.id, {
        role: 'user',
        privileges,
        assigned_journal_ids: privileges.all_journals ? [] : journalDraft[user.id] || [],
        ...extras,
      });
      await load();
      setMsg(success);
    } catch {
      setError('Could not save those privileges.');
    } finally {
      setBusy(null);
    }
  };

  const fullyApprove = async (user: AdminUser) => {
    setPrivDraft((prev) => ({ ...prev, [user.id]: fullPrivileges() }));
    setBusy(user.id);
    setMsg('');
    setError('');
    try {
      await adminApi.updateUser(user.id, {
        role: 'user',
        approval: 'full',
        assigned_journal_ids: [],
      });
      await load();
      setMsg(`Fully approved ${user.username} for every service.`);
    } catch {
      setError('Could not fully approve that account.');
    } finally {
      setBusy(null);
    }
  };

  const restrictUser = async (user: AdminUser) => {
    setBusy(`${user.id}-restricted`);
    setMsg('');
    setError('');
    try {
      await adminApi.updateUser(user.id, { approval: 'restrict' });
      await load();
      setMsg(`Restricted ${user.username}.`);
    } catch {
      setError('Could not restrict that account.');
    } finally {
      setBusy(null);
    }
  };

  const restoreAccess = async (user: AdminUser) => {
    await savePrivileges(user, { access_status: 'approved' }, `Restored access for ${user.username}.`);
  };

  const addUser = async (e: React.FormEvent, fully = false) => {
    e.preventDefault();
    setBusy('create');
    setMsg('');
    setError('');
    try {
      const createdName = username;
      const privileges = fully ? fullPrivileges() : createPriv;
      await adminApi.createUser({
        email,
        username,
        password,
        full_name: fullName || undefined,
        role: 'user',
        privileges,
        assigned_journal_ids: privileges.all_journals ? [] : createJournalIds,
        access_status: 'approved',
      });
      setEmail('');
      setUsername('');
      setFullName('');
      setPassword('');
      setCreatePriv(emptyPrivileges());
      setCreateJournalIds([]);
      await load();
      setMsg(
        fully
          ? `Fully approved ${createdName} for every service. Stay signed in.`
          : `Added ${createdName} with the ticked services. Stay signed in. Give them their email and password privately.`,
      );
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Could not add that user.');
    } finally {
      setBusy(null);
    }
  };

  const addAuthorJournal = async () => {
    const name = newJournalName.trim();
    if (!name) return;
    setBusy('journal');
    setMsg('');
    setError('');
    try {
      await citationApi.authorArticles.addJournal({ name });
      setNewJournalName('');
      setShowNewJournal(false);
      await load();
      setMsg(`Added journal “${name}” to the author-database list.`);
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Could not add that journal name.');
    } finally {
      setBusy(null);
    }
  };

  const pending = users.filter((user) => statusOf(user) === 'pending');
  const others = users.filter((user) => statusOf(user) !== 'pending');

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Admin</h2>
      <p className="text-gray-400 text-sm mb-4 max-w-3xl">
        Add a user, then tick the services they may use. Citation project asks which journals stay
        active. Article review asks which branches (English checking or reference check). Fully
        approve grants every service; restrict blocks the account; partial access is whatever you
        tick.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="mb-4">
        <button className="btn-primary" type="button" onClick={() => setShowAdd((open) => !open)}>
          {showAdd ? 'Close add user' : 'Add user'}
        </button>
      </div>

      <div className="panel p-4 mb-6 max-w-3xl">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-medium">Author-database journals</h3>
            <p className="text-xs text-gray-500 mt-1">
              These names appear in Select journal on Under process. Only admin can add a name.
            </p>
          </div>
          <button
            className="btn-secondary inline-flex items-center justify-center p-2"
            type="button"
            title="Add journal"
            onClick={() => setShowNewJournal((open) => !open)}
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
        <ul className="text-sm text-gray-300 space-y-1">
          {authorJournals.map((journal) => (
            <li key={journal.name}>{journal.name}</li>
          ))}
        </ul>
        {showNewJournal && (
          <div className="flex flex-wrap gap-2 mt-3">
            <input
              className="input-field flex-1 min-w-[16rem]"
              placeholder="New journal name"
              value={newJournalName}
              onChange={(e) => setNewJournalName(e.target.value)}
            />
            <button
              className="btn-primary"
              type="button"
              disabled={busy === 'journal'}
              onClick={() => void addAuthorJournal()}
            >
              {busy === 'journal' ? 'Saving…' : 'Save journal'}
            </button>
          </div>
        )}
      </div>

      {showAdd && (
        <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2 max-w-3xl" onSubmit={(e) => void addUser(e, false)}>
          <h3 className="md:col-span-2 text-sm font-medium">Add user</h3>
          <input
            className="input-field"
            placeholder="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            className="input-field"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            minLength={3}
            required
          />
          <input
            className="input-field"
            placeholder="Full name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
          <input
            className="input-field"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          <div className="md:col-span-2">
            <p className="text-sm text-gray-400 mb-2">Privileges</p>
            <PrivilegeChecks
              value={createPriv}
              journals={journals}
              journalIds={createJournalIds}
              onChange={setCreatePriv}
              onJournals={setCreateJournalIds}
            />
          </div>
          <div className="md:col-span-2 flex flex-wrap gap-2">
            <button className="btn-primary" type="submit" disabled={busy === 'create'}>
              {busy === 'create' ? 'Adding…' : 'Add user (ticked services)'}
            </button>
            <button
              className="btn-secondary"
              type="button"
              disabled={busy === 'create'}
              onClick={(e) => void addUser(e, true)}
            >
              Fully approve all services
            </button>
          </div>
        </form>
      )}

      {pending.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-medium mb-2">Pending approval</h3>
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="py-2 pr-3">Account</th>
                  <th className="py-2 pr-3">Privileges if approved</th>
                  <th className="py-2 pr-3" />
                </tr>
              </thead>
              <tbody>
                {pending.map((user) => (
                  <tr key={user.id} className="border-b border-gray-800/80">
                    <td className="py-3 pr-3">
                      <p className="font-medium">{user.full_name || user.username}</p>
                      <p className="text-xs text-gray-500">
                        {user.email} · {user.username}
                      </p>
                    </td>
                    <td className="py-3 pr-3">
                      <PrivilegeChecks
                        value={privDraft[user.id] || emptyPrivileges()}
                        journals={journals}
                        journalIds={journalDraft[user.id] || []}
                        onChange={(next) => setPrivDraft((prev) => ({ ...prev, [user.id]: next }))}
                        onJournals={(ids) => setJournalDraft((prev) => ({ ...prev, [user.id]: ids }))}
                      />
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="btn-primary"
                          type="button"
                          disabled={busy !== null}
                          onClick={() =>
                            void savePrivileges(
                              user,
                              { access_status: 'approved' },
                              `Approved ${user.username} for the ticked services.`,
                            )
                          }
                        >
                          Approve (partial)
                        </button>
                        <button
                          className="btn-secondary"
                          type="button"
                          disabled={busy !== null}
                          onClick={() => void fullyApprove(user)}
                        >
                          Fully approve
                        </button>
                        <button
                          className="btn-secondary"
                          type="button"
                          disabled={busy !== null}
                          onClick={() => void restrictUser(user)}
                        >
                          Restrict
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <h3 className="text-lg font-medium mb-2">Portal users</h3>
      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 pr-3">Account</th>
              <th className="py-2 pr-3">Access</th>
              <th className="py-2 pr-3">Privileges</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {others.map((user) => {
              const status = statusOf(user);
              const self = user.id === current?.id;
              const operator = isOperator(user);
              return (
                <tr key={user.id} className="border-b border-gray-800/80">
                  <td className="py-3 pr-3">
                    <p className="font-medium">{user.full_name || user.username}</p>
                    <p className="text-xs text-gray-500">
                      {user.email} · {user.username}
                      {operator ? ' · operator' : ''}
                    </p>
                  </td>
                  <td className="py-3 pr-3">
                    <span className={status === 'restricted' ? 'text-red-400' : 'text-earth-400'}>
                      {statusLabel(status)}
                    </span>
                  </td>
                  <td className="py-3 pr-3">
                    {operator ? (
                      <p className="text-xs text-gray-500">Every service</p>
                    ) : (
                      <PrivilegeChecks
                        value={privDraft[user.id] || emptyPrivileges()}
                        journals={journals}
                        journalIds={journalDraft[user.id] || []}
                        disabled={self}
                        onChange={(next) => setPrivDraft((prev) => ({ ...prev, [user.id]: next }))}
                        onJournals={(ids) => setJournalDraft((prev) => ({ ...prev, [user.id]: ids }))}
                      />
                    )}
                  </td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-2">
                      {!operator && (
                        <>
                          <button
                            className="btn-secondary"
                            type="button"
                            disabled={busy !== null || self}
                            onClick={() => void savePrivileges(user)}
                          >
                            Save privileges
                          </button>
                          <button
                            className="btn-secondary"
                            type="button"
                            disabled={busy !== null || self}
                            onClick={() => void fullyApprove(user)}
                          >
                            Fully approve
                          </button>
                        </>
                      )}
                      {status === 'approved' ? (
                        <button
                          className="btn-secondary"
                          type="button"
                          disabled={busy !== null || self}
                          onClick={() => void restrictUser(user)}
                        >
                          Restrict
                        </button>
                      ) : (
                        <button
                          className="btn-primary"
                          type="button"
                          disabled={busy !== null || self}
                          onClick={() => void restoreAccess(user)}
                        >
                          Restore access
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
