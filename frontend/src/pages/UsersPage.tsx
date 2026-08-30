import { useEffect, useState } from 'react';
import { adminApi } from '@/services/api';
import { useAuthStore } from '@/store/authStore';

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

function citationRole(user: AdminUser): 'admin' | 'user' {
  if (user.is_superuser || (user.roles || []).includes('admin')) return 'admin';
  return 'user';
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

export default function UsersPage() {
  const current = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [draft, setDraft] = useState<Record<number, 'admin' | 'user'>>({});
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | string | null>(null);
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [newRole, setNewRole] = useState<'admin' | 'user'>('user');

  const load = async () => {
    const { data } = await adminApi.users();
    const rows = data as AdminUser[];
    setUsers(rows);
    setDraft(Object.fromEntries(rows.map((row) => [row.id, citationRole(row)])));
  };

  useEffect(() => {
    void load();
  }, []);

  const saveRole = async (user: AdminUser) => {
    const role = draft[user.id] || citationRole(user);
    setBusy(user.id);
    setMsg('');
    setError('');
    try {
      await adminApi.updateUser(user.id, { role });
      await load();
      setMsg(`Saved ${user.username} as ${role}.`);
    } catch {
      setError('Could not assign that role.');
    } finally {
      setBusy(null);
    }
  };

  const setStatus = async (user: AdminUser, access_status: 'approved' | 'restricted', role?: 'admin' | 'user') => {
    setBusy(`${user.id}-${access_status}`);
    setMsg('');
    setError('');
    try {
      const payload: Record<string, unknown> = { access_status };
      if (access_status === 'approved') {
        payload.role = role || draft[user.id] || citationRole(user);
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

  const addUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy('create');
    setMsg('');
    setError('');
    try {
      const createdName = username;
      const createdRole = newRole;
      await adminApi.createUser({
        email,
        username,
        password,
        full_name: fullName || undefined,
        role: newRole,
      });
      setEmail('');
      setUsername('');
      setFullName('');
      setPassword('');
      setNewRole('user');
      await load();
      setMsg(`Added ${createdName} as ${createdRole}. They can sign in now.`);
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

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Users & access</h2>
      <p className="text-gray-400 text-sm mb-4 max-w-3xl">
        Add people and assign Admin or User. Self-registered accounts wait here until you approve
        them. Restrict anyone to block portal access.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2 max-w-3xl" onSubmit={(e) => void addUser(e)}>
        <h3 className="md:col-span-2 text-sm font-medium">Add new user</h3>
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
        <select
          className="input-field"
          value={newRole}
          onChange={(e) => setNewRole(e.target.value as 'admin' | 'user')}
        >
          <option value="user">User — New manuscript only</option>
          <option value="admin">Admin — full portal</option>
        </select>
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
                  <th className="py-2 pr-3">Role if approved</th>
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
                      <select
                        className="input-field max-w-xs"
                        value={draft[user.id] || 'user'}
                        onChange={(e) =>
                          setDraft((prev) => ({ ...prev, [user.id]: e.target.value as 'admin' | 'user' }))
                        }
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="py-3 flex flex-wrap gap-2">
                      <button
                        className="btn-primary"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => void setStatus(user, 'approved', draft[user.id] || 'user')}
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
              <th className="py-2 pr-3">Role</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {others.map((user) => {
              const status = statusOf(user);
              const self = user.id === current?.id;
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
                    <select
                      className="input-field max-w-xs"
                      value={draft[user.id] || citationRole(user)}
                      disabled={self}
                      onChange={(e) =>
                        setDraft((prev) => ({ ...prev, [user.id]: e.target.value as 'admin' | 'user' }))
                      }
                    >
                      <option value="admin">Admin</option>
                      <option value="user">User</option>
                    </select>
                  </td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="btn-secondary"
                        type="button"
                        disabled={busy !== null || self}
                        onClick={() => void saveRole(user)}
                      >
                        Save role
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
                          onClick={() => void setStatus(user, 'approved', draft[user.id])}
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
