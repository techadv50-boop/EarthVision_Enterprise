import { useEffect, useState } from 'react';
import { adminApi, citationApi } from '@/services/api';
import { ADMIN_DESKS, isFullAdmin, useAuthStore, type AdminDeskId } from '@/store/authStore';

interface AdminUser {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  desks?: string[];
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

function desksOf(user: AdminUser): AdminDeskId[] {
  if (isOperator(user)) return ADMIN_DESKS.map((d) => d.id);
  const fromApi = user.desks || [];
  if (fromApi.length) {
    return ADMIN_DESKS.map((d) => d.id).filter((id) => fromApi.includes(id));
  }
  return ADMIN_DESKS.map((d) => d.id).filter((id) => (user.roles || []).includes(`admin_${id}`));
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

function DeskChecks({
  value,
  allDesks,
  disabled,
  onAllDesks,
  onToggle,
  allowAllDesks,
}: {
  value: AdminDeskId[];
  allDesks: boolean;
  disabled?: boolean;
  onAllDesks?: (on: boolean) => void;
  onToggle: (desk: AdminDeskId, on: boolean) => void;
  allowAllDesks: boolean;
}) {
  return (
    <div className="space-y-2 min-w-[14rem]">
      {allowAllDesks && onAllDesks && (
        <label className="flex items-center gap-2 text-xs font-medium">
          <input
            type="checkbox"
            checked={allDesks}
            disabled={disabled}
            onChange={(e) => onAllDesks(e.target.checked)}
          />
          All desks (operator)
        </label>
      )}
      {ADMIN_DESKS.map((desk) => (
        <label key={desk.id} className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={allDesks || value.includes(desk.id)}
            disabled={disabled || allDesks}
            onChange={(e) => onToggle(desk.id, e.target.checked)}
          />
          <span>
            Admin for {desk.label.toLowerCase()}
            <span className="block text-gray-500 font-normal">{desk.hint}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

export default function UsersPage() {
  const current = useAuthStore((s) => s.user);
  const canGrantAll = isFullAdmin(current);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [deskDraft, setDeskDraft] = useState<Record<number, AdminDeskId[]>>({});
  const [allDraft, setAllDraft] = useState<Record<number, boolean>>({});
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | string | null>(null);
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [createDesks, setCreateDesks] = useState<AdminDeskId[]>([]);
  const [createAll, setCreateAll] = useState(false);
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [journalDraft, setJournalDraft] = useState<Record<number, number[]>>({});
  const [createJournalIds, setCreateJournalIds] = useState<number[]>([]);

  const load = async () => {
    try {
      const [{ data }, journalsRes] = await Promise.all([
        adminApi.users(),
        citationApi.journals.list().catch(() => ({ data: [] as JournalOption[] })),
      ]);
      const rows = data as AdminUser[];
      setUsers(rows);
      setDeskDraft(Object.fromEntries(rows.map((row) => [row.id, desksOf(row)])));
      setAllDraft(Object.fromEntries(rows.map((row) => [row.id, isOperator(row)])));
      setJournalDraft(
        Object.fromEntries(rows.map((row) => [row.id, row.assigned_journal_ids || []])),
      );
      setJournals((journalsRes.data || []) as JournalOption[]);
    } catch {
      setError('Could not load the user list. You can still add a user below.');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const saveDesks = async (user: AdminUser) => {
    setBusy(user.id);
    setMsg('');
    setError('');
    try {
      const all = Boolean(allDraft[user.id]);
      await adminApi.updateUser(user.id, all ? { role: 'admin' } : { role: 'user', desks: deskDraft[user.id] || [] });
      await load();
      setMsg(`Saved desks for ${user.username}.`);
    } catch {
      setError('Could not assign those desks.');
    } finally {
      setBusy(null);
    }
  };

  const setStatus = async (user: AdminUser, access_status: 'approved' | 'restricted') => {
    setBusy(`${user.id}-${access_status}`);
    setMsg('');
    setError('');
    try {
      const payload: Record<string, unknown> = { access_status };
      if (access_status === 'approved') {
        const all = Boolean(allDraft[user.id]);
        payload.role = all ? 'admin' : 'user';
        if (!all) payload.desks = deskDraft[user.id] || [];
      }
      await adminApi.updateUser(user.id, payload);
      await load();
      setMsg(
        access_status === 'approved'
          ? `Approved ${user.username} for portal access.`
          : `Restricted ${user.username}.`,
      );
    } catch {
      setError('Could not update access.');
    } finally {
      setBusy(null);
    }
  };

  const saveJournals = async (user: AdminUser) => {
    setBusy(`journals-${user.id}`);
    setMsg('');
    setError('');
    try {
      await adminApi.updateUser(user.id, { assigned_journal_ids: journalDraft[user.id] || [] });
      await load();
      setMsg(`Saved journal access for ${user.username}.`);
    } catch {
      setError('Could not save journal access.');
    } finally {
      setBusy(null);
    }
  };

  const toggleJournal = (userId: number, journalId: number, on: boolean) => {
    setJournalDraft((prev) => {
      const next = new Set(prev[userId] || []);
      if (on) next.add(journalId);
      else next.delete(journalId);
      return { ...prev, [userId]: [...next] };
    });
  };

  const toggleCreateJournal = (journalId: number, on: boolean) => {
    setCreateJournalIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(journalId);
      else next.delete(journalId);
      return [...next];
    });
  };

  const addUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy('create');
    setMsg('');
    setError('');
    try {
      const createdName = username;
      await adminApi.createUser({
        email,
        username,
        password,
        full_name: fullName || undefined,
        role: createAll ? 'admin' : 'user',
        desks: createAll ? [] : createDesks,
        assigned_journal_ids: createAll || createDesks.includes('citation') ? [] : createJournalIds,
      });
      setEmail('');
      setUsername('');
      setFullName('');
      setPassword('');
      setCreateDesks([]);
      setCreateAll(false);
      setCreateJournalIds([]);
      await load();
      setMsg(
        `Added ${createdName}. Stay signed in. Give them their email and password privately — they can sign in now.`,
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

  const pending = users.filter((user) => statusOf(user) === 'pending');
  const others = users.filter((user) => statusOf(user) !== 'pending');
  const staffJournals = !createAll && !createDesks.includes('citation');

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Adding users</h2>
      <p className="text-gray-400 text-sm mb-4 max-w-3xl">
        Tick the desks this person administers. Citation project, author database, article review,
        adding users, and galley composition can each have a different admin. Leave every desk
        unticked for a staff account that only works assigned journals.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2 max-w-3xl" onSubmit={(e) => void addUser(e)}>
        <h3 className="md:col-span-2 text-sm font-medium">Add a person while you stay signed in</h3>
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
          <p className="text-sm text-gray-400 mb-2">Admin desks</p>
          <DeskChecks
            value={createDesks}
            allDesks={createAll}
            allowAllDesks={canGrantAll}
            onAllDesks={setCreateAll}
            onToggle={(desk, on) =>
              setCreateDesks((prev) => {
                const next = new Set(prev);
                if (on) next.add(desk);
                else next.delete(desk);
                return [...next];
              })
            }
          />
        </div>
        {staffJournals && journals.length > 0 && (
          <div className="md:col-span-2 space-y-2">
            <p className="text-sm text-gray-400">Journals this staff account may see and cite from</p>
            <div className="flex flex-wrap gap-3">
              {journals.map((journal) => (
                <label key={journal.id} className="inline-flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createJournalIds.includes(journal.id)}
                    onChange={(e) => toggleCreateJournal(journal.id, e.target.checked)}
                  />
                  {journal.abbreviation || journal.name}
                </label>
              ))}
            </div>
          </div>
        )}
        <button className="btn-primary" type="submit" disabled={busy === 'create'}>
          {busy === 'create' ? 'Adding…' : 'Add user & grant access'}
        </button>
      </form>

      {pending.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-medium mb-2">Pending approval</h3>
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="py-2 pr-3">Account</th>
                  <th className="py-2 pr-3">Desks if approved</th>
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
                      <DeskChecks
                        value={deskDraft[user.id] || []}
                        allDesks={Boolean(allDraft[user.id])}
                        allowAllDesks={canGrantAll}
                        onAllDesks={(on) => setAllDraft((prev) => ({ ...prev, [user.id]: on }))}
                        onToggle={(desk, on) =>
                          setDeskDraft((prev) => {
                            const next = new Set(prev[user.id] || []);
                            if (on) next.add(desk);
                            else next.delete(desk);
                            return { ...prev, [user.id]: [...next] };
                          })
                        }
                      />
                    </td>
                    <td className="py-3 flex flex-wrap gap-2">
                      <button
                        className="btn-primary"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => void setStatus(user, 'approved')}
                      >
                        Approve
                      </button>
                      <button
                        className="btn-secondary"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => void setStatus(user, 'restricted')}
                      >
                        Restrict
                      </button>
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
              <th className="py-2 pr-3">Admin desks</th>
              <th className="py-2 pr-3">Journals</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {others.map((user) => {
              const status = statusOf(user);
              const self = user.id === current?.id;
              const all = Boolean(allDraft[user.id]);
              return (
                <tr key={user.id} className="border-b border-gray-800/80">
                  <td className="py-3 pr-3">
                    <p className="font-medium">{user.full_name || user.username}</p>
                    <p className="text-xs text-gray-500">
                      {user.email} · {user.username}
                    </p>
                  </td>
                  <td className="py-3 pr-3">
                    <span className={status === 'restricted' ? 'text-red-400' : 'text-earth-400'}>
                      {statusLabel(status)}
                    </span>
                  </td>
                  <td className="py-3 pr-3">
                    <DeskChecks
                      value={deskDraft[user.id] || []}
                      allDesks={all}
                      disabled={self}
                      allowAllDesks={canGrantAll}
                      onAllDesks={(on) => setAllDraft((prev) => ({ ...prev, [user.id]: on }))}
                      onToggle={(desk, on) =>
                        setDeskDraft((prev) => {
                          const next = new Set(prev[user.id] || []);
                          if (on) next.add(desk);
                          else next.delete(desk);
                          return { ...prev, [user.id]: [...next] };
                        })
                      }
                    />
                  </td>
                  <td className="py-3 pr-3">
                    {all || (deskDraft[user.id] || []).includes('citation') ? (
                      <p className="text-xs text-gray-500">All citation journals</p>
                    ) : journals.length === 0 ? (
                      <p className="text-xs text-gray-500">Add a journal first</p>
                    ) : (
                      <div className="space-y-2 min-w-[12rem]">
                        {journals.map((journal) => (
                          <label key={journal.id} className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={(journalDraft[user.id] || []).includes(journal.id)}
                              disabled={self}
                              onChange={(e) => toggleJournal(user.id, journal.id, e.target.checked)}
                            />
                            <span>{journal.abbreviation || journal.name}</span>
                          </label>
                        ))}
                        <button
                          className="btn-secondary"
                          type="button"
                          disabled={busy !== null || self}
                          onClick={() => void saveJournals(user)}
                        >
                          Save journals
                        </button>
                      </div>
                    )}
                  </td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="btn-secondary"
                        type="button"
                        disabled={busy !== null || self}
                        onClick={() => void saveDesks(user)}
                      >
                        Save desks
                      </button>
                      {status === 'approved' ? (
                        <button
                          className="btn-secondary"
                          type="button"
                          disabled={busy !== null || self}
                          onClick={() => void setStatus(user, 'restricted')}
                        >
                          Restrict
                        </button>
                      ) : (
                        <button
                          className="btn-primary"
                          type="button"
                          disabled={busy !== null || self}
                          onClick={() => void setStatus(user, 'approved')}
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
