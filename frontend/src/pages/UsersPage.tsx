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
}

function citationRole(user: AdminUser): 'admin' | 'user' {
  if (user.is_superuser || (user.roles || []).includes('admin')) return 'admin';
  return 'user';
}

export default function UsersPage() {
  const current = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [draft, setDraft] = useState<Record<number, 'admin' | 'user'>>({});
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  const load = async () => {
    const { data } = await adminApi.users();
    const rows = data as AdminUser[];
    setUsers(rows);
    setDraft(Object.fromEntries(rows.map((row) => [row.id, citationRole(row)])));
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async (user: AdminUser) => {
    const role = draft[user.id] || citationRole(user);
    setBusy(user.id);
    setMsg('');
    try {
      await adminApi.updateUser(user.id, { role });
      await load();
      setMsg(`Saved ${user.username} as ${role}.`);
    } catch {
      setMsg('Could not assign that role.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Users & roles</h2>
      <p className="text-gray-400 text-sm mb-4 max-w-3xl">
        Admin sees Journals, Search, New manuscript, and this page. User sees only New manuscript.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 pr-3">Account</th>
              <th className="py-2 pr-3">Role</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
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
                    value={draft[user.id] || citationRole(user)}
                    disabled={user.id === current?.id}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, [user.id]: e.target.value as 'admin' | 'user' }))
                    }
                  >
                    <option value="admin">Admin</option>
                    <option value="user">User</option>
                  </select>
                </td>
                <td className="py-3">
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={busy === user.id || user.id === current?.id}
                    onClick={() => void save(user)}
                  >
                    {busy === user.id ? 'Saving…' : 'Assign role'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
