import { useCallback, useEffect, useState } from 'react';
import { Shield, UserPlus, X, Loader2 } from 'lucide-react';
import {
  adminService,
  type AdminUser,
  type ClientRole,
} from '../../services/adminService';
import { getErrorMessage } from '../../services/api';
import { TOOLBOXES, type ToolboxId } from '../../toolbox/catalog';
import { SatelliteAdminSection } from './SatelliteAdminSection';

const ROLES: ClientRole[] = ['analyst', 'viewer', 'billing', 'admin'];

const ALL_TOOL_IDS = TOOLBOXES.map((t) => t.id);

type AdminTab = 'clients' | 'satellites';

interface Props {
  onClose: () => void;
}

export function AdminPanel({ onClose }: Props) {
  const [tab, setTab] = useState<AdminTab>('clients');
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [organization, setOrganization] = useState('');
  const [role, setRole] = useState<ClientRole>('analyst');
  const [allTools, setAllTools] = useState(true);
  const [tools, setTools] = useState<ToolboxId[]>([...ALL_TOOL_IDS]);
  const [isActive, setIsActive] = useState(true);
  const [mode, setMode] = useState<'create' | 'edit'>('create');

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminService.listUsers();
      setUsers(data.items);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const resetForm = () => {
    setMode('create');
    setSelectedId(null);
    setEmail('');
    setPassword('');
    setFullName('');
    setOrganization('');
    setRole('analyst');
    setAllTools(true);
    setTools([...ALL_TOOL_IDS]);
    setIsActive(true);
    setMessage(null);
    setError(null);
  };

  const selectUser = (u: AdminUser) => {
    setMode('edit');
    setSelectedId(u.id);
    setEmail(u.email);
    setPassword('');
    setFullName(u.full_name);
    setOrganization(u.organization || '');
    setRole(u.role);
    setIsActive(u.is_active);
    if (u.allowed_tools == null) {
      setAllTools(true);
      setTools([...ALL_TOOL_IDS]);
    } else {
      setAllTools(false);
      setTools(u.allowed_tools.filter((id): id is ToolboxId =>
        ALL_TOOL_IDS.includes(id as ToolboxId),
      ));
    }
    setMessage(null);
    setError(null);
  };

  const toggleTool = (id: ToolboxId) => {
    setTools((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    const allowed_tools = allTools || role === 'admin' ? null : [...tools];
    try {
      if (mode === 'create') {
        await adminService.createUser({
          email,
          password,
          full_name: fullName,
          role,
          organization: organization || undefined,
          allowed_tools,
        });
        setMessage(`Created account for ${email}`);
      } else if (selectedId) {
        await adminService.updateUser(selectedId, {
          full_name: fullName,
          organization: organization || null,
          role,
          is_active: isActive,
          allowed_tools,
        });
        setMessage(`Updated ${email}`);
      }
      await loadUsers();
      if (mode === 'create') resetForm();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-10 sm:pt-16">
      <div className="ev-card w-full max-w-3xl p-4 sm:p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 font-display text-lg font-semibold">
              <Shield className="h-5 w-5 text-[var(--accent)]" />
              Admin
            </h2>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Manage client accounts and satellite catalog APIs for every client.
            </p>
          </div>
          <button type="button" className="ev-btn-ghost p-2" onClick={onClose} title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-4 flex gap-2 border-b border-[var(--line)] pb-2">
          <button
            type="button"
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'clients'
                ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('clients')}
          >
            Client accounts
          </button>
          <button
            type="button"
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'satellites'
                ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('satellites')}
          >
            Satellites / APIs
          </button>
        </div>

        {tab === 'satellites' && <SatelliteAdminSection />}

        {tab === 'clients' && (
        <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
          <section className="rounded-lg border border-[var(--line)] p-3">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                Accounts
              </h3>
              <button type="button" className="ev-btn-ghost text-xs" onClick={resetForm}>
                <UserPlus className="mr-1 inline h-3.5 w-3.5" />
                New
              </button>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 py-6 text-xs text-[var(--muted)]">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </div>
            ) : (
              <ul className="max-h-72 space-y-1 overflow-y-auto">
                {users.map((u) => (
                  <li key={u.id}>
                    <button
                      type="button"
                      onClick={() => selectUser(u)}
                      className={`w-full rounded-md px-2 py-2 text-left text-sm transition ${
                        selectedId === u.id
                          ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                          : 'hover:bg-[var(--bg)]'
                      }`}
                    >
                      <div className="truncate font-medium">{u.full_name}</div>
                      <div className="truncate text-[10px] text-[var(--muted)]">
                        {u.email} · {u.role}
                        {!u.is_active ? ' · inactive' : ''}
                        {u.allowed_tools == null
                          ? ' · all tools'
                          : ` · ${u.allowed_tools.length} tools`}
                      </div>
                    </button>
                  </li>
                ))}
                {!users.length && (
                  <li className="py-4 text-center text-xs text-[var(--muted)]">No users yet</li>
                )}
              </ul>
            )}
          </section>

          <form onSubmit={onSubmit} className="rounded-lg border border-[var(--line)] p-3">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
              {mode === 'create' ? 'Create client' : 'Edit client'}
            </h3>

            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
              Full name
            </label>
            <input
              className="ev-input mb-2"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />

            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">Email</label>
            <input
              className="ev-input mb-2"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={mode === 'edit'}
            />

            {mode === 'create' && (
              <>
                <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
                  Temporary password
                </label>
                <input
                  className="ev-input mb-2"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
              </>
            )}

            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
              Organization
            </label>
            <input
              className="ev-input mb-2"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
            />

            <div className="mb-2 grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
                  Role
                </label>
                <select
                  className="ev-input"
                  value={role}
                  onChange={(e) => setRole(e.target.value as ClientRole)}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
              {mode === 'edit' && (
                <div className="flex items-end pb-1">
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={isActive}
                      onChange={(e) => setIsActive(e.target.checked)}
                    />
                    Active
                  </label>
                </div>
              )}
            </div>

            <div className="mb-2 mt-3 border-t border-[var(--line)] pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted)]">
                  Tool permissions
                </span>
                <label className="flex items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    checked={allTools || role === 'admin'}
                    disabled={role === 'admin'}
                    onChange={(e) => setAllTools(e.target.checked)}
                  />
                  All toolboxes
                </label>
              </div>
              {!allTools && role !== 'admin' && (
                <div className="grid max-h-40 grid-cols-2 gap-1.5 overflow-y-auto">
                  {TOOLBOXES.map((box) => (
                    <label
                      key={box.id}
                      className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-[var(--bg)]"
                    >
                      <input
                        type="checkbox"
                        checked={tools.includes(box.id)}
                        onChange={() => toggleTool(box.id)}
                      />
                      {box.title}
                    </label>
                  ))}
                </div>
              )}
              {(allTools || role === 'admin') && (
                <p className="text-[11px] text-[var(--muted)]">
                  {role === 'admin'
                    ? 'Admins always have access to every toolbox.'
                    : 'This account can use every toolbox.'}
                </p>
              )}
            </div>

            {error && (
              <div className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {error}
              </div>
            )}
            {message && (
              <div className="mb-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                {message}
              </div>
            )}

            <button type="submit" className="ev-btn-primary w-full" disabled={saving}>
              {saving
                ? 'Saving…'
                : mode === 'create'
                  ? 'Create account'
                  : 'Save changes'}
            </button>
          </form>
        </div>
        )}
      </div>
    </div>
  );
}
