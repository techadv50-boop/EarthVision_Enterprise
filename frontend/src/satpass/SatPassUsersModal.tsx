import { useEffect, useState } from 'react';
import { X, Check, Ban, Loader2, RotateCcw, Plus } from 'lucide-react';
import { adminApi } from '@/services/api';
import { useAuthStore } from '@/store/authStore';
import { QuietSecretInput, QuietTextInput } from '@/components/QuietField';

interface AdminUser {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  access_status?: string;
}

type Role = 'admin' | 'user';
type Status = 'pending' | 'approved' | 'restricted';

function roleOf(u: AdminUser): Role {
  return u.is_superuser || (u.roles || []).includes('admin') ? 'admin' : 'user';
}

function statusOf(u: AdminUser): Status {
  const v = (u.access_status || (u.is_active ? 'approved' : 'restricted')).toLowerCase();
  return v === 'pending' || v === 'restricted' ? (v as Status) : 'approved';
}

const STATUS_STYLE: Record<Status, string> = {
  pending: 'text-amber-400',
  approved: 'text-emerald-400',
  restricted: 'text-red-400',
};

export default function SatPassUsersModal({ onClose }: { onClose: () => void }) {
  const current = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [draftRole, setDraftRole] = useState<Record<number, Role>>({});
  const [busy, setBusy] = useState<number | 'create' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [draftPassword, setDraftPassword] = useState<Record<number, string>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newUsername, setNewUsername] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<Role>('user');
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const { data } = await adminApi.users();
      const rows = data as AdminUser[];
      setUsers(rows);
      setDraftRole(Object.fromEntries(rows.map((r) => [r.id, roleOf(r)])));
    } catch {
      setError('Could not load users.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const update = async (u: AdminUser, payload: Record<string, unknown>) => {
    setBusy(u.id);
    setError('');
    try {
      await adminApi.updateUser(u.id, payload);
      await load();
    } catch {
      setError('Update failed.');
    } finally {
      setBusy(null);
    }
  };

  const approve = (u: AdminUser) => update(u, { access_status: 'approved', role: draftRole[u.id] || 'user' });
  const restrict = (u: AdminUser) => update(u, { access_status: 'restricted' });
  const saveRole = (u: AdminUser) => update(u, { role: draftRole[u.id] || roleOf(u) });

  const savePassword = async (u: AdminUser) => {
    const password = (draftPassword[u.id] || '').trim();
    if (password.length < 8) {
      setNotice('');
      setError('Password must be at least 8 characters.');
      return;
    }
    setBusy(u.id);
    setError('');
    setNotice('');
    try {
      await adminApi.updateUser(u.id, { password });
      setDraftPassword((prev) => ({ ...prev, [u.id]: '' }));
      setNotice(`Password updated for ${u.username}.`);
    } catch {
      setError('Could not update that password.');
    } finally {
      setBusy(null);
    }
  };

  const addUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.trim().length < 8) {
      setNotice('');
      setError('Password must be at least 8 characters.');
      return;
    }
    setBusy('create');
    setError('');
    setNotice('');
    try {
      await adminApi.createUser({
        email: newEmail.trim(),
        username: newUsername.trim(),
        password: newPassword,
        full_name: newName.trim() || undefined,
        role: newRole,
      });
      setNewEmail('');
      setNewUsername('');
      setNewName('');
      setNewPassword('');
      setNewRole('user');
      setShowAdd(false);
      await load();
      setNotice(`Added ${newUsername.trim()}. They can sign in now.`);
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

  const removeAccount = async (u: AdminUser) => {
    if (u.id === current?.id) return;
    if (confirmDelete !== u.id) {
      setConfirmDelete(u.id);
      setError('');
      setNotice(`Click Confirm delete to remove ${u.username}.`);
      return;
    }
    setBusy(u.id);
    setError('');
    setNotice('');
    try {
      await adminApi.deleteUser(u.id);
      setConfirmDelete(null);
      setNotice(`Deleted ${u.username}.`);
      await load();
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Could not delete that account.');
    } finally {
      setBusy(null);
    }
  };

  const passwordRow = (u: AdminUser) => (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <QuietSecretInput
        value={draftPassword[u.id] || ''}
        onChange={(e) => setDraftPassword((prev) => ({ ...prev, [u.id]: e.target.value }))}
        placeholder="New password"
        className="min-w-0 flex-1 rounded bg-gray-950 px-2 py-1 text-xs text-gray-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500"
      />
      <button
        disabled={busy === u.id}
        onClick={() => void savePassword(u)}
        className="rounded bg-cyan-600 px-2 py-1 text-xs font-medium hover:bg-cyan-500 disabled:opacity-50"
      >
        Set password
      </button>
      <button
        type="button"
        disabled={busy === u.id || u.id === current?.id}
        title={u.id === current?.id ? 'You cannot delete the account you are signed in with' : 'Delete this account'}
        onClick={() => void removeAccount(u)}
        className="rounded bg-white/5 px-2 py-1 text-xs text-red-300 ring-1 ring-red-500/30 hover:bg-red-500/10 disabled:opacity-50"
      >
        {confirmDelete === u.id ? 'Confirm delete' : 'Delete'}
      </button>
    </div>
  );

  const pending = users.filter((u) => statusOf(u) === 'pending');
  const others = users.filter((u) => statusOf(u) !== 'pending');

  const roleSelect = (u: AdminUser) => (
    <select
      value={draftRole[u.id] || roleOf(u)}
      disabled={u.id === current?.id}
      onChange={(e) => setDraftRole((p) => ({ ...p, [u.id]: e.target.value as Role }))}
      className="rounded bg-gray-900 px-1.5 py-1 text-xs text-gray-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500 disabled:opacity-50"
    >
      <option value="user">User</option>
      <option value="admin">Admin</option>
    </select>
  );

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-lg bg-gray-950 ring-1 ring-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <h2 className="text-sm font-bold">Users &amp; access</h2>
            <p className="text-[11px] text-gray-500">
              Add accounts, set any password, and approve, restrict, or delete access.
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-4 py-3">
          {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
          {notice && <p className="mb-2 text-xs text-emerald-400">{notice}</p>}
          {loading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading users…
            </div>
          ) : (
            <>
              <div className="mb-4">
                <button
                  type="button"
                  onClick={() => setShowAdd((v) => !v)}
                  className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-xs text-cyan-300 ring-1 ring-cyan-500/40 hover:bg-white/10"
                >
                  <Plus className="h-3.5 w-3.5" /> {showAdd ? 'Close new user' : 'Add user'}
                </button>
                {showAdd && (
                  <form
                    onSubmit={(e) => void addUser(e)}
                    autoComplete="off"
                    className="mt-2 space-y-2 rounded bg-gray-900/70 p-2 ring-1 ring-white/10"
                  >
                    <div className="grid gap-2 sm:grid-cols-2">
                      <QuietTextInput
                        name="satpass-email"
                        inputMode="email"
                        required
                        value={newEmail}
                        onChange={(e) => setNewEmail(e.target.value)}
                        placeholder="Email"
                        className="rounded bg-gray-950 px-2 py-1 text-xs outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      />
                      <QuietTextInput
                        name="satpass-username"
                        required
                        minLength={3}
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                        placeholder="Username"
                        className="rounded bg-gray-950 px-2 py-1 text-xs outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      />
                      <QuietTextInput
                        name="satpass-name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="Full name"
                        className="rounded bg-gray-950 px-2 py-1 text-xs outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      />
                      <QuietSecretInput
                        required
                        minLength={8}
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        placeholder="Password"
                        className="rounded bg-gray-950 px-2 py-1 text-xs outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <select
                        value={newRole}
                        onChange={(e) => setNewRole(e.target.value as Role)}
                        className="rounded bg-gray-950 px-1.5 py-1 text-xs text-gray-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                      <button
                        type="submit"
                        disabled={busy === 'create'}
                        className="rounded bg-cyan-600 px-2 py-1 text-xs font-medium hover:bg-cyan-500 disabled:opacity-50"
                      >
                        {busy === 'create' ? 'Adding…' : 'Create account'}
                      </button>
                    </div>
                  </form>
                )}
              </div>
              {pending.length > 0 && (
                <div className="mb-4">
                  <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-amber-400">
                    Pending approval ({pending.length})
                  </h3>
                  <div className="space-y-1.5">
                    {pending.map((u) => (
                      <div
                        key={u.id}
                        className="rounded bg-gray-900/70 p-2 ring-1 ring-white/10"
                      >
                        <div className="flex items-center gap-2">
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">{u.full_name || u.username}</p>
                            <p className="truncate text-[11px] text-gray-500">
                              {u.email} · {u.username}
                            </p>
                          </div>
                          {roleSelect(u)}
                          <button
                            disabled={busy === u.id}
                            onClick={() => approve(u)}
                            className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs font-medium hover:bg-emerald-500 disabled:opacity-50"
                          >
                            <Check className="h-3.5 w-3.5" /> Approve
                          </button>
                          <button
                            disabled={busy === u.id}
                            onClick={() => restrict(u)}
                            className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-xs text-gray-300 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
                          >
                            <Ban className="h-3.5 w-3.5" /> Restrict
                          </button>
                        </div>
                        {passwordRow(u)}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-400">
                All users ({others.length})
              </h3>
              <div className="space-y-1.5">
                {others.map((u) => {
                  const status = statusOf(u);
                  const self = u.id === current?.id;
                  return (
                    <div
                      key={u.id}
                      className="rounded bg-gray-900/70 p-2 ring-1 ring-white/10"
                    >
                      <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {u.full_name || u.username}
                          {self && <span className="ml-1 text-[10px] text-cyan-400">(you)</span>}
                        </p>
                        <p className="truncate text-[11px] text-gray-500">
                          {u.email} ·{' '}
                          <span className={STATUS_STYLE[status]}>{status}</span>
                        </p>
                      </div>
                      {roleSelect(u)}
                      <button
                        disabled={busy === u.id || self}
                        onClick={() => saveRole(u)}
                        className="rounded bg-white/5 px-2 py-1 text-xs text-gray-300 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
                      >
                        Save role
                      </button>
                      {status === 'approved' ? (
                        <button
                          disabled={busy === u.id || self}
                          onClick={() => restrict(u)}
                          className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-xs text-red-300 ring-1 ring-red-500/30 hover:bg-red-500/10 disabled:opacity-50"
                        >
                          <Ban className="h-3.5 w-3.5" /> Restrict
                        </button>
                      ) : (
                        <button
                          disabled={busy === u.id}
                          onClick={() => approve(u)}
                          className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs font-medium hover:bg-emerald-500 disabled:opacity-50"
                        >
                          <RotateCcw className="h-3.5 w-3.5" /> Restore
                        </button>
                      )}
                      </div>
                      {passwordRow(u)}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
