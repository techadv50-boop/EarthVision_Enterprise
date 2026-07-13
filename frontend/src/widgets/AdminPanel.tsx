import { useEffect, useState } from 'react';
import { CreditCard, Key, Users, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import { api, getErrorMessage } from '../services/api';
import { useAuthStore } from '../store/authStore';

export function AdminPanel() {
  const { activePanel, setActivePanel } = useMapStore();
  const user = useAuthStore((s) => s.user);
  const [plans, setPlans] = useState<Array<Record<string, unknown>>>([]);
  const [subscription, setSubscription] = useState<Record<string, unknown> | null>(null);
  const [apiKeys, setApiKeys] = useState<Array<Record<string, unknown>>>([]);
  const [users, setUsers] = useState<Array<Record<string, unknown>>>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [rawKey, setRawKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'billing' | 'keys' | 'users'>('billing');

  useEffect(() => {
    if (activePanel !== 'admin') return;
    Promise.all([
      api.get('/subscriptions/plans'),
      api.get('/subscriptions/me'),
      api.get('/api-keys'),
    ])
      .then(([p, s, k]) => {
        setPlans(p.data);
        setSubscription(s.data);
        setApiKeys(k.data);
      })
      .catch((err) => setError(getErrorMessage(err)));

    if (user?.role === 'admin') {
      api
        .get('/users')
        .then((r) => setUsers(r.data.items))
        .catch(() => undefined);
    }
  }, [activePanel, user?.role]);

  if (activePanel !== 'admin') return null;

  const upgrade = async (plan: string) => {
    try {
      const { data } = await api.post('/subscriptions/upgrade', { plan });
      setSubscription(data);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const createKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const { data } = await api.post('/api-keys', { name: newKeyName.trim() });
      setRawKey(data.raw_key);
      setApiKeys((prev) => [data, ...prev]);
      setNewKeyName('');
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <aside className="pointer-events-auto absolute right-3 top-20 z-20 w-[min(100%-1.5rem,26rem)] animate-fade-up md:right-4">
      <div className="ev-panel max-h-[calc(100vh-8rem)] overflow-y-auto p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">Administration</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mb-3 flex gap-1">
          {(
            [
              ['billing', CreditCard, 'Billing'],
              ['keys', Key, 'API Keys'],
              ['users', Users, 'Users'],
            ] as const
          ).map(([id, Icon, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`ev-btn-ghost flex-1 text-[10px] ${tab === id ? 'bg-orbit-500/20 text-orbit-400' : ''}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
        {error && <p className="mb-2 text-xs text-red-400">{error}</p>}

        {tab === 'billing' && (
          <div className="space-y-2">
            {subscription && (
              <div className="rounded-lg bg-earth-950/50 p-3 text-xs">
                <div className="text-earth-400">Current plan</div>
                <div className="font-display text-lg text-orbit-400">
                  {String(subscription.plan).toUpperCase()}
                </div>
                <div className="mt-1 text-earth-300">
                  Scenes {String(subscription.scenes_used)} / {String(subscription.scene_quota)}
                </div>
                <div className="text-earth-300">
                  ML credits {String(subscription.ml_credits_used)} / {String(subscription.ml_credits)}
                </div>
              </div>
            )}
            {plans.map((plan) => (
              <div key={String(plan.plan)} className="rounded-lg border border-earth-700/50 p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">{String(plan.name)}</div>
                    <div className="text-xs text-earth-400">${String(plan.monthly_price)}/mo</div>
                  </div>
                  <button
                    type="button"
                    className="ev-btn-primary text-[10px]"
                    onClick={() => upgrade(String(plan.plan))}
                  >
                    Select
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'keys' && (
          <div>
            <div className="mb-2 flex gap-2">
              <input
                className="ev-input"
                placeholder="Key name"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
              />
              <button type="button" className="ev-btn-primary" onClick={createKey}>
                Create
              </button>
            </div>
            {rawKey && (
              <p className="mb-2 break-all rounded bg-earth-950 p-2 font-mono text-[10px] text-soil-400">
                Copy now: {rawKey}
              </p>
            )}
            <ul className="space-y-1">
              {apiKeys.map((k) => (
                <li key={String(k.id)} className="rounded-lg bg-earth-950/50 px-2 py-2 text-xs">
                  <div className="font-medium">{String(k.name)}</div>
                  <div className="font-mono text-earth-500">{String(k.key_prefix)}…</div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === 'users' && (
          <div>
            {user?.role !== 'admin' ? (
              <p className="text-xs text-earth-400">Admin role required to manage users.</p>
            ) : (
              <ul className="space-y-1">
                {users.map((u) => (
                  <li key={String(u.id)} className="rounded-lg bg-earth-950/50 px-2 py-2 text-xs">
                    <div className="font-medium">{String(u.full_name)}</div>
                    <div className="text-earth-400">
                      {String(u.email)} · {String(u.role)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
