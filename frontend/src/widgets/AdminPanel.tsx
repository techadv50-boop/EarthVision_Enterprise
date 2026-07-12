import { useEffect, useState } from 'react';
import {
  Shield, Users, Key, CreditCard, FolderOpen, Plus, Trash2,
} from 'lucide-react';
import { adminApi } from '@/services/api';
import api from '@/services/api';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';

interface AdminStats {
  total_users: number;
  active_users: number;
  total_projects: number;
  total_scenes_cached: number;
  total_analysis_jobs: number;
  storage_used_gb: number;
}

interface UserRow {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
}

interface ProjectRow {
  id: number;
  name: string;
  description?: string;
}

interface SubscriptionInfo {
  plan: string;
  status: string;
  scenes_limit?: number;
  scenes_used?: number;
  max_scenes_per_month?: number;
  max_storage_gb?: number;
  max_api_calls_per_day?: number;
}

export default function AdminPanel() {
  const { user } = useAuthStore();
  const { showNotification } = useUIStore();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [apiKeys, setApiKeys] = useState<
    Array<{ id: number; name: string; prefix: string; is_active: boolean }>
  >([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('');
  const [tab, setTab] = useState<'overview' | 'users' | 'projects' | 'billing'>('overview');

  useEffect(() => {
    if (user?.is_superuser) void loadStats();
    void loadApiKeys();
    void loadProjects();
    void loadSubscription();
    if (user?.is_superuser) void loadUsers();
  }, [user]);

  const loadStats = async () => {
    try {
      const { data } = await adminApi.stats();
      setStats(data);
    } catch {
      /* ignore */
    }
  };

  const loadUsers = async () => {
    try {
      const { data } = await adminApi.users();
      setUsers(data);
    } catch {
      /* ignore */
    }
  };

  const loadProjects = async () => {
    try {
      const { data } = await adminApi.projects.list();
      setProjects(data);
    } catch {
      /* ignore */
    }
  };

  const loadSubscription = async () => {
    try {
      const { data } = await adminApi.subscription();
      setSubscription({
        ...data,
        scenes_limit: data.scenes_limit ?? data.max_scenes_per_month,
      });
    } catch {
      try {
        const { data } = await api.get('/billing/status');
        setSubscription({
          ...data,
          scenes_limit: data.scenes_limit ?? data.max_scenes_per_month,
        });
      } catch {
        /* ignore */
      }
    }
  };

  const handleCheckout = async (plan: string) => {
    try {
      const { data } = await api.post('/billing/checkout', { plan });
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        showNotification(data.message || `Plan set to ${plan} (Stripe not configured)`, 'info');
        await loadSubscription();
      }
    } catch {
      showNotification('Checkout failed', 'error');
    }
  };

  const handleToggleUser = async (id: number, isActive: boolean) => {
    try {
      await api.patch(`/admin/users/${id}`, { is_active: !isActive });
      await loadUsers();
      showNotification('User updated', 'success');
    } catch {
      showNotification('Failed to update user', 'error');
    }
  };

  const loadApiKeys = async () => {
    try {
      const { data } = await adminApi.apiKeys.list();
      setApiKeys(data);
    } catch {
      /* ignore */
    }
  };

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const { data } = await adminApi.apiKeys.create(newKeyName);
      setCreatedKey(data.key);
      setNewKeyName('');
      await loadApiKeys();
      showNotification('API key created — copy it now', 'success');
    } catch {
      showNotification('Failed to create API key', 'error');
    }
  };

  const handleRevokeKey = async (id: number) => {
    try {
      await adminApi.apiKeys.revoke(id);
      await loadApiKeys();
      showNotification('API key revoked', 'success');
    } catch {
      showNotification('Failed to revoke key', 'error');
    }
  };

  const handleCreateProject = async () => {
    if (!projectName.trim()) return;
    try {
      await adminApi.projects.create({ name: projectName.trim(), description: '' });
      setProjectName('');
      await loadProjects();
      showNotification('Project created', 'success');
    } catch {
      showNotification('Failed to create project', 'error');
    }
  };

  if (!user) return null;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <Shield className="w-4 h-4" /> Administration
      </h3>

      <div className="flex gap-1 flex-wrap">
        {(['overview', 'users', 'projects', 'billing'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-2 py-1 text-xs rounded capitalize ${
              tab === t ? 'bg-earth-600 text-white' : 'bg-gray-800 text-gray-400'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          {user.is_superuser && stats && (
            <div className="grid grid-cols-2 gap-2">
              {[
                { icon: Users, label: 'Users', value: stats.total_users },
                { icon: FolderOpen, label: 'Projects', value: stats.total_projects },
                { icon: CreditCard, label: 'Scenes', value: stats.total_scenes_cached },
                { icon: Shield, label: 'Jobs', value: stats.total_analysis_jobs },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} className="panel p-3 text-center">
                  <Icon className="w-4 h-4 mx-auto text-earth-400 mb-1" />
                  <div className="text-lg font-bold">{value}</div>
                  <div className="text-xs text-gray-500">{label}</div>
                </div>
              ))}
              <div className="panel p-3 text-center col-span-2">
                <div className="text-sm font-mono">{stats.storage_used_gb.toFixed(2)} GB</div>
                <div className="text-xs text-gray-500">Storage used</div>
              </div>
            </div>
          )}

          <div>
            <label className="text-xs text-gray-500 mb-2 flex items-center gap-1">
              <Key className="w-3 h-3" /> API Keys
            </label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Key name..."
                className="input-field text-sm"
              />
              <button onClick={handleCreateKey} className="btn-primary text-sm">
                Create
              </button>
            </div>
            {createdKey && (
              <div className="panel p-2 mb-2 text-xs font-mono break-all text-green-400">
                {createdKey}
              </div>
            )}
            <div className="space-y-1">
              {apiKeys.map((key) => (
                <div
                  key={key.id}
                  className="flex items-center justify-between p-2 rounded bg-gray-800/50 text-sm"
                >
                  <span>{key.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-500">{key.prefix}...</span>
                    <button onClick={() => void handleRevokeKey(key.id)} className="text-red-400">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {tab === 'users' && (
        <div className="space-y-1 max-h-64 overflow-y-auto">
          {!user.is_superuser && (
            <p className="text-xs text-gray-500">Superuser access required</p>
          )}
          {users.map((u) => (
            <div key={u.id} className="flex justify-between items-center p-2 rounded bg-gray-800/50 text-sm gap-2">
              <div className="min-w-0">
                <div>{u.username}</div>
                <div className="text-xs text-gray-500 truncate">{u.email}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs text-gray-400">
                  {u.is_superuser ? 'admin' : u.is_active ? 'active' : 'inactive'}
                </span>
                {!u.is_superuser && (
                  <button
                    onClick={() => void handleToggleUser(u.id, u.is_active)}
                    className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600"
                  >
                    {u.is_active ? 'Disable' : 'Enable'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'projects' && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="New project..."
              className="input-field text-sm"
            />
            <button onClick={handleCreateProject} className="btn-primary px-3">
              <Plus className="w-4 h-4" />
            </button>
          </div>
          {projects.map((p) => (
            <div key={p.id} className="p-2 rounded bg-gray-800/50 text-sm">
              <div className="font-medium">{p.name}</div>
              {p.description && (
                <div className="text-xs text-gray-500">{p.description}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'billing' && (
        <div className="panel p-3 space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <CreditCard className="w-4 h-4 text-earth-400" />
            Subscription
          </div>
          {subscription ? (
            <>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">Plan</span>
                <span className="capitalize">{subscription.plan}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">Status</span>
                <span className="capitalize">{subscription.status}</span>
              </div>
              {(subscription.scenes_limit ?? subscription.max_scenes_per_month) != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Scenes / month</span>
                  <span>
                    {subscription.scenes_used ?? 0} /{' '}
                    {subscription.scenes_limit ?? subscription.max_scenes_per_month}
                  </span>
                </div>
              )}
              {subscription.max_storage_gb != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Storage</span>
                  <span>{subscription.max_storage_gb} GB</span>
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-gray-500">No subscription data</p>
          )}
          <div className="grid grid-cols-3 gap-1">
            {['free', 'pro', 'enterprise'].map((plan) => (
              <button
                key={plan}
                onClick={() => void handleCheckout(plan)}
                className="text-xs px-2 py-1.5 rounded border border-gray-700 hover:border-earth-500 capitalize"
              >
                {plan}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="text-xs text-gray-500">
        Role: {user.roles.join(', ') || 'none'}
        {user.is_superuser && ' · Superuser'}
      </div>
    </div>
  );
}
