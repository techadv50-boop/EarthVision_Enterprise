import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Loader2, ShieldBan, UserPlus, X } from 'lucide-react';
import {
  adminService,
  type AccountDecisionPayload,
  type AdminUser,
  type ClientRole,
} from '../../services/adminService';
import type { AccountStatus } from '../../services/authService';
import { getErrorMessage } from '../../services/api';
import { satelliteService, type SatelliteAdmin } from '../../services/satelliteService';
import { TOOLBOXES, type ToolboxId } from '../../toolbox/catalog';

const ROLES: ClientRole[] = ['analyst', 'viewer', 'billing', 'admin'];
const ALL_TOOL_IDS = TOOLBOXES.map((t) => t.id);

const STATUS_LABEL: Record<AccountStatus, string> = {
  pending: 'Pending approval',
  approved: 'Approved',
  declined: 'Declined',
  restricted: 'Restricted',
};

function statusClass(status: AccountStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-amber-100 text-amber-800';
    case 'approved':
      return 'bg-emerald-100 text-emerald-800';
    case 'declined':
      return 'bg-red-100 text-red-800';
    case 'restricted':
      return 'bg-sky-100 text-sky-800';
    default:
      return 'bg-slate-100 text-slate-700';
  }
}

export function ClientAdminSection() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [satellites, setSatellites] = useState<SatelliteAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | AccountStatus>('all');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [organization, setOrganization] = useState('');
  const [role, setRole] = useState<ClientRole>('analyst');
  const [allTools, setAllTools] = useState(true);
  const [tools, setTools] = useState<ToolboxId[]>([...ALL_TOOL_IDS]);
  const [allSats, setAllSats] = useState(true);
  const [satNames, setSatNames] = useState<string[]>([]);
  const [isActive, setIsActive] = useState(true);
  const [accountStatus, setAccountStatus] = useState<AccountStatus>('approved');
  const [mode, setMode] = useState<'create' | 'edit'>('create');

  const pendingCount = useMemo(
    () => users.filter((u) => (u.account_status || 'approved') === 'pending').length,
    [users],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [userData, satData] = await Promise.all([
        adminService.listUsers(1, 100),
        satelliteService.listAdmin(),
      ]);
      setUsers(userData.items);
      setSatellites(satData);
      setSatNames((prev) => (prev.length ? prev : satData.map((s) => s.name)));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
    setAllSats(true);
    setSatNames(satellites.map((s) => s.name));
    setIsActive(true);
    setAccountStatus('approved');
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
    setAccountStatus(u.account_status || 'approved');
    if (u.allowed_tools == null) {
      setAllTools(true);
      setTools([...ALL_TOOL_IDS]);
    } else {
      setAllTools(false);
      setTools(
        u.allowed_tools.filter((id): id is ToolboxId =>
          ALL_TOOL_IDS.includes(id as ToolboxId),
        ),
      );
    }
    if (u.allowed_satellites == null) {
      setAllSats(true);
      setSatNames(satellites.map((s) => s.name));
    } else {
      setAllSats(false);
      setSatNames([...u.allowed_satellites]);
    }
    setMessage(null);
    setError(null);
  };

  const toggleTool = (id: ToolboxId) => {
    setTools((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  };

  const toggleSat = (name: string) => {
    setSatNames((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const resolvedTools = (): string[] | null =>
    allTools || role === 'admin' ? null : [...tools];

  const resolvedSats = (): string[] | null =>
    allSats || role === 'admin' ? null : [...satNames];

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      if (mode === 'create') {
        await adminService.createUser({
          email,
          password,
          full_name: fullName,
          role,
          organization: organization || undefined,
          allowed_tools: resolvedTools(),
          allowed_satellites: resolvedSats(),
          account_status: accountStatus,
          is_active: accountStatus === 'approved' || accountStatus === 'restricted',
        });
        setMessage(`Created account for ${email}`);
        resetForm();
      } else if (selectedId) {
        await adminService.updateUser(selectedId, {
          full_name: fullName,
          organization: organization || null,
          role,
          is_active: isActive,
          allowed_tools: resolvedTools(),
          allowed_satellites: resolvedSats(),
          account_status: accountStatus,
        });
        setMessage(`Updated ${email}`);
      }
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const decide = async (status: AccountDecisionPayload['status']) => {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await adminService.decideAccount(selectedId, {
        status,
        role: role === 'admin' ? 'analyst' : role,
        allowed_tools: status === 'declined' ? [] : resolvedTools(),
        allowed_satellites: status === 'declined' ? [] : resolvedSats(),
      });
      setMessage(
        status === 'approved'
          ? `Approved ${updated.email}`
          : status === 'declined'
            ? `Declined ${updated.email}`
            : `Restricted services for ${updated.email}`,
      );
      await load();
      selectUser(updated);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const visibleUsers = users.filter((u) =>
    filter === 'all' ? true : (u.account_status || 'approved') === filter,
  );

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_1.25fr]">
      <section className="rounded-lg border border-[var(--line)] p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Client accounts
            {pendingCount > 0 && (
              <span className="ml-2 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                {pendingCount} pending
              </span>
            )}
          </h3>
          <button type="button" className="ev-btn-ghost text-xs" onClick={resetForm}>
            <UserPlus className="mr-1 inline h-3.5 w-3.5" />
            New
          </button>
        </div>

        <div className="mb-2 flex flex-wrap gap-1">
          {(
            [
              ['all', 'All'],
              ['pending', 'Pending'],
              ['approved', 'Approved'],
              ['restricted', 'Restricted'],
              ['declined', 'Declined'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter(id)}
              className={`rounded-md px-2 py-1 text-[10px] font-semibold ${
                filter === id
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[var(--bg)] text-[var(--muted)] hover:text-[var(--ink)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-[var(--muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : (
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {visibleUsers.map((u) => {
              const status = (u.account_status || 'approved') as AccountStatus;
              return (
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
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate font-medium">{u.full_name}</div>
                      <span
                        className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase ${statusClass(status)}`}
                      >
                        {status}
                      </span>
                    </div>
                    <div className="truncate text-[10px] text-[var(--muted)]">
                      {u.email} · {u.role}
                      {!u.is_active ? ' · inactive' : ''}
                      {u.allowed_tools == null
                        ? ' · all tools'
                        : ` · ${u.allowed_tools.length} tools`}
                      {u.allowed_satellites == null
                        ? ' · all sats'
                        : ` · ${u.allowed_satellites.length} sats`}
                    </div>
                  </button>
                </li>
              );
            })}
            {!visibleUsers.length && (
              <li className="py-4 text-center text-xs text-[var(--muted)]">
                No accounts in this filter
              </li>
            )}
          </ul>
        )}
      </section>

      <form onSubmit={onSubmit} className="rounded-lg border border-[var(--line)] p-3">
        <h3 className="mb-1 text-sm font-semibold text-[var(--ink)]">
          {mode === 'create' ? 'Add client account' : 'Control client account'}
        </h3>
        <p className="mb-3 text-[11px] text-[var(--muted)]">
          Admin only. Approve / decline / restrict access, and choose which tools and
          satellites this account may use. Clients cannot add satellite APIs.
        </p>

        {mode === 'edit' && selectedId && role !== 'admin' && (
          <div className="mb-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="ev-btn inline-flex items-center gap-1 bg-emerald-600 text-white hover:brightness-110"
              disabled={saving}
              onClick={() => void decide('approved')}
            >
              <Check className="h-3.5 w-3.5" />
              Approve
            </button>
            <button
              type="button"
              className="ev-btn inline-flex items-center gap-1 bg-sky-700 text-white hover:brightness-110"
              disabled={saving}
              onClick={() => void decide('restricted')}
            >
              <ShieldBan className="h-3.5 w-3.5" />
              Restrict
            </button>
            <button
              type="button"
              className="ev-btn inline-flex items-center gap-1 bg-red-600 text-white hover:brightness-110"
              disabled={saving}
              onClick={() => void decide('declined')}
            >
              <X className="h-3.5 w-3.5" />
              Decline
            </button>
          </div>
        )}

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
          <div>
            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
              Account status
            </label>
            <select
              className="ev-input"
              value={accountStatus}
              onChange={(e) => setAccountStatus(e.target.value as AccountStatus)}
              disabled={role === 'admin'}
            >
              {(Object.keys(STATUS_LABEL) as AccountStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
          </div>
        </div>

        {mode === 'edit' && (
          <label className="mb-3 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              disabled={role === 'admin'}
            />
            Active (can sign in when approved/restricted)
          </label>
        )}

        <div className="mb-3 border-t border-[var(--line)] pt-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted)]">
              Allowed tools
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
            <div className="grid max-h-36 grid-cols-2 gap-1.5 overflow-y-auto">
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
        </div>

        <div className="mb-3 border-t border-[var(--line)] pt-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted)]">
              Allowed satellites
            </span>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={allSats || role === 'admin'}
                disabled={role === 'admin'}
                onChange={(e) => setAllSats(e.target.checked)}
              />
              All satellites
            </label>
          </div>
          {!allSats && role !== 'admin' && (
            <div className="grid max-h-36 grid-cols-2 gap-1.5 overflow-y-auto">
              {satellites.map((sat) => (
                <label
                  key={sat.id}
                  className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-[var(--bg)]"
                >
                  <input
                    type="checkbox"
                    checked={satNames.includes(sat.name)}
                    onChange={() => toggleSat(sat.name)}
                  />
                  {sat.label}
                </label>
              ))}
              {!satellites.length && (
                <p className="col-span-2 text-[11px] text-[var(--muted)]">
                  No satellites configured yet — add them under Satellites / APIs.
                </p>
              )}
            </div>
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
              ? 'Create client account'
              : 'Save account controls'}
        </button>
      </form>
    </div>
  );
}
