import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Satellite,
  Search,
  Plus,
  Trash2,
  Crosshair,
  Loader2,
  X,
  Users,
  LogOut,
} from 'lucide-react';
import { satelliteApi, type SavedSatellite, type TleResult } from '@/services/api';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';
import SatPassMap, { type TrackedSat } from './SatPassMap';
import SatPassUsersModal from './SatPassUsersModal';
import PredictView from './PredictView';
import type { SatState } from './orbit';
import { catalogSensor } from './predict/catalog';

const PALETTE = [
  '#22d3ee',
  '#f472b6',
  '#a3e635',
  '#fbbf24',
  '#60a5fa',
  '#f87171',
  '#c084fc',
  '#34d399',
];

const PRESETS: { name: string; q: string }[] = [
  { name: 'ISS (ZARYA)', q: '25544' },
  { name: 'PRSS-1', q: '43530' },
  { name: 'Hubble (HST)', q: '20580' },
  { name: 'NOAA-19', q: '33591' },
  { name: 'Landsat-9', q: '49260' },
  { name: 'Sentinel-2A', q: '40697' },
];

const DEFAULT_SWATH_KM = 60;

function toTracked(s: SavedSatellite, color: string): TrackedSat {
  const norad = s.norad_id ?? noradFromLine1(s.tle_line1);
  const sensor = catalogSensor(s.name, norad);
  return {
    id: s.id,
    name: s.name,
    line1: s.tle_line1,
    line2: s.tle_line2,
    color: s.color || color,
    visible: true,
    swathKm: sensor.swathKm ?? DEFAULT_SWATH_KM,
    noradId: s.norad_id,
  };
}

function noradFromLine1(line1: string): number | null {
  const n = parseInt(line1.slice(2, 7).trim(), 10);
  return Number.isFinite(n) ? n : null;
}

function isPlaceholderName(name: string | null | undefined): boolean {
  const n = (name || '').trim().toLowerCase();
  if (!n) return true;
  if (/^norad\s+\d+$/i.test(n)) return true;
  return ['custom satellite', 'custom sat', 'customsat', 'custom', 'unnamed', 'unknown'].includes(
    n,
  );
}

/** Parse a pasted TLE block (optional name line + the two element lines). */
function parseTleBlock(text: string): { name: string | null; line1: string; line2: string } | null {
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const l1 = lines.find((l) => l.startsWith('1 '));
  const l2 = lines.find((l) => l.startsWith('2 '));
  if (!l1 || !l2) return null;
  const nameLine = lines.find((l) => !l.startsWith('1 ') && !l.startsWith('2 '));
  return { name: nameLine || null, line1: l1, line2: l2 };
}

export default function SatPassPage() {
  const [mode, setMode] = useState<'track' | 'predict'>('predict');
  const [sats, setSats] = useState<TrackedSat[]>([]);
  const [states, setStates] = useState<Record<number, SatState>>({});
  const [focusId, setFocusId] = useState<number | null>(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TleResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');

  const [showPaste, setShowPaste] = useState(false);
  const [tleText, setTleText] = useState('');
  const [showVisibility, setShowVisibility] = useState(false);
  const [showUsers, setShowUsers] = useState(false);

  const navigate = useNavigate();
  // ProtectedRoute already loads the current user; here we only read it.
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const admin = isCitationAdmin(user);

  const handleStates = useCallback((s: Record<number, SatState>) => setStates(s), []);

  const nextColor = useMemo(() => {
    const used = new Set(sats.map((s) => s.color));
    return PALETTE.find((c) => !used.has(c)) ?? PALETTE[sats.length % PALETTE.length];
  }, [sats]);

  useEffect(() => {
    satelliteApi
      .list()
      .then(({ data }) => setSats(data.map((s, i) => toTracked(s, PALETTE[i % PALETTE.length]))))
      .catch(() => undefined);
  }, []);

  const addFromTle = async (name: string, line1: string, line2: string, noradId?: number | null) => {
    setError('');
    const color = nextColor;
    try {
      const { data } = await satelliteApi.add({ name, line1, line2, norad_id: noradId, color });
      setSats((prev) => [...prev, toTracked(data, color)]);
      return true;
    } catch {
      setError('Could not add satellite (check the TLE lines).');
      return false;
    }
  };

  const runSearch = async (q: string) => {
    const term = q.trim();
    if (!term) return;
    setSearching(true);
    setError('');
    setResults([]);
    try {
      const { data } = await satelliteApi.fetch(term);
      setResults(data.slice(0, 12));
      if (data.length === 0) setError(`No satellite found for "${term}".`);
    } catch {
      setError(`No satellite found for "${term}".`);
    } finally {
      setSearching(false);
    }
  };

  const addPreset = async (q: string) => {
    setSearching(true);
    setError('');
    try {
      const { data } = await satelliteApi.fetch(q);
      if (data[0]) await addFromTle(data[0].name, data[0].line1, data[0].line2, data[0].norad_id);
    } catch {
      setError('Lookup failed. Try again.');
    } finally {
      setSearching(false);
    }
  };

  const remove = async (id: number) => {
    setSats((prev) => prev.filter((s) => s.id !== id));
    try {
      await satelliteApi.remove(id);
    } catch {
      /* ignore */
    }
  };

  const toggle = (id: number) =>
    setSats((prev) => prev.map((s) => (s.id === id ? { ...s, visible: !s.visible } : s)));

  const setSwath = (id: number, swathKm: number) =>
    setSats((prev) =>
      prev.map((s) => (s.id === id ? { ...s, swathKm: Math.max(1, swathKm || 1) } : s)),
    );

  const submitPaste = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseTleBlock(tleText);
    if (!parsed) {
      setError('Paste a valid TLE — a line starting with "1 " and one starting with "2 ".');
      return;
    }
    const norad = noradFromLine1(parsed.line1);
    let name = parsed.name?.trim() || '';
    setSearching(true);
    setError('');
    try {
      if (norad && isPlaceholderName(name)) {
        try {
          const { data } = await satelliteApi.fetch(String(norad));
          const catalogName = data[0]?.name?.trim();
          if (catalogName && !isPlaceholderName(catalogName)) {
            name = catalogName;
          }
        } catch {
          /* keep pasted/fallback name if Celestrak is unreachable */
        }
      }
      if (isPlaceholderName(name)) {
        name = norad ? `NORAD ${norad}` : 'Custom satellite';
      }
      const ok = await addFromTle(name, parsed.line1, parsed.line2, norad);
      if (ok) {
        setTleText('');
        setShowPaste(false);
      }
    } finally {
      setSearching(false);
    }
  };

  const tabBtn = (id: 'track' | 'predict', label: string) => (
    <button
      onClick={() => setMode(id)}
      className={`rounded px-3 py-1.5 text-sm font-medium ${
        mode === id ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:bg-white/10 hover:text-white'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-black text-gray-100">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-white/10 bg-gray-950 px-4">
        <Satellite className="h-6 w-6 text-cyan-400" />
        <div className="min-w-0">
          <h1 className="text-base font-bold tracking-wide">SatPass</h1>
        </div>
        <nav className="ml-2 flex items-center gap-1 rounded-md bg-white/5 p-0.5 ring-1 ring-white/10">
          {tabBtn('track', 'Track')}
          {tabBtn('predict', 'Predict')}
        </nav>
        <p className="hidden truncate text-[11px] text-gray-500 sm:block">
          {mode === 'predict'
            ? 'When will this satellite pass over a location or area?'
            : 'satpass.xdgen.com · live satellite tracker'}
        </p>
        <div className="ml-auto flex items-center gap-1">
          {admin && (
            <button
              onClick={() => setShowUsers(true)}
              title="Manage user access"
              className="rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-cyan-400"
            >
              <Users className="h-4 w-4" />
            </button>
          )}
          <button
            onClick={() => {
              logout();
              navigate('/login');
            }}
            title={user ? `Sign out ${user.username}` : 'Sign out'}
            className="rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-red-400"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      {mode === 'predict' ? (
        <PredictView key={user?.id ?? 'predict'} trackedSats={sats} />
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* Control panel (sidebar) */}
      <aside className="flex h-full w-[360px] max-w-[92vw] shrink-0 flex-col border-r border-white/10 bg-gray-950">
        {user && (
          <div className="border-b border-white/10 px-4 py-1.5 text-[11px] text-gray-500">
            Signed in as <span className="text-gray-300">{user.full_name || user.username}</span>
            {admin ? ' · admin' : ' · user'}
          </div>
        )}

        <div className="space-y-4 overflow-y-auto px-4 py-4">
          {/* Add by search */}
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-400">
              Add satellite
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-gray-500" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && runSearch(query)}
                  placeholder="Name or NORAD id (e.g. ISS, 25544)"
                  className="w-full rounded bg-gray-900 py-2 pl-8 pr-2 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                />
              </div>
              <button
                onClick={() => runSearch(query)}
                disabled={searching}
                className="rounded bg-cyan-600 px-3 text-sm font-medium hover:bg-cyan-500 disabled:opacity-50"
              >
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Find'}
              </button>
            </div>

            <div className="mt-2 flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.q}
                  onClick={() => addPreset(p.q)}
                  className="rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-gray-300 ring-1 ring-white/10 hover:bg-white/10"
                >
                  + {p.name}
                </button>
              ))}
            </div>

            <button
              onClick={() => setShowPaste((v) => !v)}
              className="mt-2 inline-flex items-center gap-1 rounded bg-white/5 px-2.5 py-1 text-[11px] text-cyan-300 ring-1 ring-cyan-500/40 hover:bg-white/10"
            >
              <Plus className="h-3.5 w-3.5" /> {showPaste ? 'Close TLE input' : 'Add by TLE'}
            </button>

            {showPaste && (
              <form onSubmit={submitPaste} className="mt-2 space-y-2">
                <textarea
                  value={tleText}
                  onChange={(e) => setTleText(e.target.value)}
                  rows={3}
                  placeholder={
                    'Paste a full TLE, e.g.\nISS (ZARYA)\n1 25544U ...\n2 25544 ...'
                  }
                  className="w-full rounded bg-gray-900 px-2 py-1.5 font-mono text-[11px] leading-tight outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                />
                <button
                  type="submit"
                  disabled={searching}
                  className="inline-flex items-center gap-1 rounded bg-cyan-600 px-3 py-1.5 text-sm font-medium hover:bg-cyan-500 disabled:opacity-50"
                >
                  {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}{' '}
                  Add satellite
                </button>
              </form>
            )}

            {error && <p className="mt-2 text-xs text-red-400">{error}</p>}

            {/* Search results */}
            {results.length > 0 && (
              <div className="mt-2 space-y-1 rounded bg-gray-900/70 p-2 ring-1 ring-white/10">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-gray-400">{results.length} result(s)</span>
                  <button onClick={() => setResults([])} className="text-gray-500 hover:text-white">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                {results.map((r) => (
                  <button
                    key={`${r.norad_id}-${r.name}`}
                    onClick={async () => {
                      const ok = await addFromTle(r.name, r.line1, r.line2, r.norad_id);
                      if (ok) setResults([]);
                    }}
                    className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-white/10"
                  >
                    <span className="truncate">{r.name}</span>
                    <span className="ml-2 shrink-0 text-[11px] text-gray-500">
                      {r.norad_id ?? ''}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tracked list */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="block text-xs font-medium uppercase tracking-wide text-gray-400">
                Tracked ({sats.length})
              </label>
              <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
                <input
                  type="checkbox"
                  checked={showVisibility}
                  onChange={() => setShowVisibility((v) => !v)}
                  className="h-3.5 w-3.5 accent-cyan-500"
                />
                Visibility circle
              </label>
            </div>
            {sats.length === 0 && (
              <p className="text-xs text-gray-500">
                Nothing yet — search for a satellite or tap a preset above.
              </p>
            )}
            <div className="space-y-1.5">
              {sats.map((s) => {
                const st = states[s.id];
                return (
                  <div
                    key={s.id}
                    className="rounded bg-gray-900/70 p-2 ring-1 ring-white/10"
                  >
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={s.visible}
                        onChange={() => toggle(s.id)}
                        className="h-4 w-4 accent-cyan-500"
                        title="Show / hide"
                      />
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: s.color }}
                      />
                      <span className="flex-1 truncate text-sm font-medium">{s.name}</span>
                      <button
                        onClick={() => setFocusId(s.id)}
                        title="Fly to"
                        className="text-gray-400 hover:text-cyan-400"
                      >
                        <Crosshair className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => remove(s.id)}
                        title="Remove"
                        className="text-gray-400 hover:text-red-400"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    {st && (
                      <div className="mt-1 grid grid-cols-4 gap-1 pl-6 text-[11px] text-gray-400">
                        <span title="Latitude">LAT {st.lat.toFixed(2)}</span>
                        <span title="Longitude">LNG {st.lon.toFixed(2)}</span>
                        <span title="Altitude (km)">ALT {st.altKm.toFixed(0)}</span>
                        <span title="Speed (km/s)">SPD {st.speedKmS.toFixed(2)}</span>
                      </div>
                    )}
                    <div className="mt-1 flex items-center gap-1.5 pl-6 text-[11px] text-gray-400">
                      <span title="Imaging swath width">Swath</span>
                      <input
                        type="number"
                        min={1}
                        value={s.swathKm}
                        onChange={(e) => setSwath(s.id, Number(e.target.value))}
                        className="w-16 rounded bg-gray-900 px-1.5 py-0.5 text-[11px] text-gray-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                      />
                      <span>km</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="mt-auto border-t border-white/10 px-4 py-2 text-[10px] text-gray-600">
          Orbits propagated with SGP4 · TLEs from Celestrak
        </div>
      </aside>

      {/* Map play area */}
      <div className="relative flex-1">
        <SatPassMap
          sats={sats}
          onStates={handleStates}
          focusId={focusId}
          showVisibility={showVisibility}
        />
      </div>
        </div>
      )}

      {showUsers && <SatPassUsersModal onClose={() => setShowUsers(false)} />}
    </div>
  );
}
