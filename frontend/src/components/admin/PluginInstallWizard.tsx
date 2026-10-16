import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ChevronRight, Upload } from 'lucide-react';
import { RESOLUTION_BANDS } from '../../constants/imageryResolution';
import { pluginService, type PluginSlot } from '../../services/pluginService';
import { satelliteService, type SatellitePublic } from '../../services/satelliteService';
import { toolTreeService, type ToolCategoryNode } from '../../services/toolTreeService';

const SLOTS: PluginSlot[] = [
  'left_toolbar',
  'right_analysis_panel',
  'map_overlay',
  'results_panel',
];

interface Props {
  categories: ToolCategoryNode[];
  onDone: () => void;
  onRefreshCategories: () => Promise<void>;
}

type Step = 1 | 2 | 3 | 4 | 5 | 6;

function flattenCategories(
  nodes: ToolCategoryNode[],
  prefix = '',
): Array<{ id: string; label: string }> {
  const out: Array<{ id: string; label: string }> = [];
  for (const n of nodes) {
    const label = prefix ? `${prefix} / ${n.name}` : n.name;
    out.push({ id: n.id, label });
    out.push(...flattenCategories(n.children || [], label));
  }
  return out;
}

export function PluginInstallWizard({ categories, onDone, onRefreshCategories }: Props) {
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [validated, setValidated] = useState<Record<string, unknown> | null>(null);
  const [installed, setInstalled] = useState<Record<string, unknown> | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [newCategoryName, setNewCategoryName] = useState('');
  const [executionSlot, setExecutionSlot] = useState<PluginSlot>('right_analysis_panel');
  const [icon, setIcon] = useState('wrench');
  const [applicableResolutions, setApplicableResolutions] = useState<string[]>([]);
  const [applicableSatellites, setApplicableSatellites] = useState<string[]>([]);
  const [satellites, setSatellites] = useState<SatellitePublic[]>([]);
  const [activateNow, setActivateNow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [placementId, setPlacementId] = useState<string | null>(null);

  const flatCats = useMemo(() => flattenCategories(categories), [categories]);

  useEffect(() => {
    void satelliteService
      .listAdmin()
      .then(setSatellites)
      .catch(() => setSatellites([]));
  }, []);

  function toggleResolution(key: string) {
    setApplicableResolutions((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }

  function toggleSatellite(name: string) {
    setApplicableSatellites((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function runValidate() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await pluginService.validateUpload(file);
      if (res.ok === false) {
        setError(String(res.error || 'Validation failed'));
        return;
      }
      setValidated(res);
      setDisplayName(String(res.name || res.plugin_id || ''));
      if (typeof res.frontend_slot === 'string' && SLOTS.includes(res.frontend_slot as PluginSlot)) {
        setExecutionSlot(res.frontend_slot as PluginSlot);
      }
      setStep(2);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Validation failed');
    } finally {
      setBusy(false);
    }
  }

  async function ensureCategory(): Promise<string> {
    if (categoryId) return categoryId;
    if (!newCategoryName.trim()) {
      throw new Error('Select or create a category');
    }
    const created = await toolTreeService.createCategory({ name: newCategoryName.trim() });
    if (created.ok === false) throw new Error(String(created.error || 'Create category failed'));
    await onRefreshCategories();
    const id = String(created.id);
    setCategoryId(id);
    return id;
  }

  async function runInstall() {
    if (!validated?.staging_id || !validated?.digest) {
      setError('Missing staging validation');
      return;
    }
    if (applicableResolutions.length === 0) {
      setError('Select at least one imagery resolution this tool works with');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const catId = await ensureCategory();
      const inst = await pluginService.installStaging(
        String(validated.staging_id),
        String(validated.digest),
      );
      if (inst.ok === false) {
        setError(String(inst.error || 'Install failed'));
        return;
      }
      setInstalled(inst);
      const place = await toolTreeService.upsertPlacement({
        plugin_id: String(validated.plugin_id || inst.plugin_id),
        category_id: catId,
        display_name: displayName || String(validated.name || validated.plugin_id),
        execution_slot: executionSlot,
        icon,
        visible: true,
        enabled: true,
        applicable_resolutions: applicableResolutions,
        applicable_satellites: applicableSatellites,
      });
      if (place.ok === false) {
        setError(String(place.error || 'Placement failed'));
        return;
      }
      setPlacementId(String(place.id));
      setStep(4);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Install failed');
    } finally {
      setBusy(false);
    }
  }

  async function runActivate() {
    const pluginId = String(validated?.plugin_id || installed?.plugin_id || '');
    const version = String(validated?.version || installed?.version || '');
    if (!pluginId || !version) {
      setError('Missing plugin version');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (activateNow) {
        const res = await pluginService.activate(pluginId, version);
        if (res.ok === false) {
          setError(String(res.error || 'Activate failed'));
          return;
        }
      }
      setStep(6);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Activate failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3" data-testid="plugin-install-wizard">
      <div className="flex flex-wrap items-center gap-1 text-[10px] uppercase tracking-wide text-[var(--muted)]">
        {[1, 2, 3, 4, 5, 6].map((s) => (
          <span key={s} className="inline-flex items-center gap-1">
            <span
              className={`rounded px-1.5 py-0.5 font-semibold ${
                step === s
                  ? 'bg-[var(--accent)] text-white'
                  : step > s
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'bg-[var(--bg)]'
              }`}
            >
              {s}
            </span>
            {s < 6 && <ChevronRight className="h-3 w-3" />}
          </span>
        ))}
      </div>

      {error && (
        <p className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
          {error}
        </p>
      )}

      {step === 1 && (
        <section className="space-y-2 rounded border border-[var(--line)] p-3">
          <h4 className="text-xs font-semibold">Step 1 — Upload</h4>
          <p className="text-[11px] text-[var(--muted)]">
            Select a signed SATEYE tool plugin package (.zip). Install never rebuilds the Host
            Platform.
          </p>
          <input
            type="file"
            accept=".zip,application/zip"
            data-testid="wizard-file"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <button
            type="button"
            disabled={!file || busy}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            onClick={() => void runValidate()}
          >
            <Upload className="h-3.5 w-3.5" />
            Validate package
          </button>
        </section>
      )}

      {step === 2 && validated && (
        <section className="space-y-2 rounded border border-[var(--line)] p-3">
          <h4 className="text-xs font-semibold">Step 2 — Validate</h4>
          <ul className="space-y-1 text-[11px]">
            <li>Plugin: {String(validated.plugin_id)}</li>
            <li>Version: {String(validated.version)}</li>
            <li>Digest: {String(validated.digest)}</li>
            <li>Publisher: {String(validated.publisher_id || '—')}</li>
            <li>Permissions: {JSON.stringify(validated.permissions || [])}</li>
          </ul>
          <button
            type="button"
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white"
            onClick={() => setStep(3)}
          >
            Continue to configure
          </button>
        </section>
      )}

      {step === 3 && (
        <section className="space-y-2 rounded border border-[var(--line)] p-3">
          <h4 className="text-xs font-semibold">Step 3 — Configure</h4>
          <label className="block text-[11px]">
            Display name
            <input
              className="mt-0.5 w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              data-testid="wizard-display-name"
            />
          </label>
          <label className="block text-[11px]">
            Parent category
            <select
              className="mt-0.5 w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              data-testid="wizard-category"
            >
              <option value="">— create new below —</option>
              {flatCats.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          {!categoryId && (
            <label className="block text-[11px]">
              New category name
              <input
                className="mt-0.5 w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                placeholder="e.g. Image Processing"
                data-testid="wizard-new-category"
              />
            </label>
          )}
          <label className="block text-[11px]">
            Execution location (interface opens here)
            <select
              className="mt-0.5 w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
              value={executionSlot}
              onChange={(e) => setExecutionSlot(e.target.value as PluginSlot)}
              data-testid="wizard-slot"
            >
              {SLOTS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px]">
            Icon key
            <input
              className="mt-0.5 w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
            />
          </label>

          <fieldset
            className="rounded border border-[var(--line)] p-2"
            data-testid="wizard-resolutions"
          >
            <legend className="px-1 text-[11px] font-semibold">
              Imagery resolutions this tool works with *
            </legend>
            <p className="mb-1.5 text-[10px] text-[var(--muted)]">
              Not all tools apply to all satellite imagery. Select every resolution band
              this tool may run against (e.g. ≤1m for VHR ship detect, ≤10m for Sentinel-2).
            </p>
            <div className="flex flex-wrap gap-1.5">
              {RESOLUTION_BANDS.map((band) => {
                const on = applicableResolutions.includes(band.key);
                return (
                  <label
                    key={band.key}
                    className={`inline-flex cursor-pointer items-center gap-1 rounded border px-2 py-1 text-[11px] ${
                      on
                        ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                        : 'border-[var(--line)]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={on}
                      onChange={() => toggleResolution(band.key)}
                    />
                    {band.label}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <fieldset
            className="rounded border border-[var(--line)] p-2"
            data-testid="wizard-satellites"
          >
            <legend className="px-1 text-[11px] font-semibold">
              Applicable satellites (optional)
            </legend>
            <p className="mb-1.5 text-[10px] text-[var(--muted)]">
              Leave empty to allow any satellite that matches the resolution tags above.
              Or pick specific providers this tool is validated for.
            </p>
            <div className="max-h-36 space-y-1 overflow-y-auto">
              {satellites.map((sat) => {
                const on = applicableSatellites.includes(sat.name);
                return (
                  <label
                    key={sat.id}
                    className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-[var(--bg)]"
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => toggleSatellite(sat.name)}
                    />
                    <span className="font-medium">{sat.label}</span>
                    <span className="text-[10px] text-[var(--muted)]">{sat.name}</span>
                  </label>
                );
              })}
              {!satellites.length && (
                <p className="text-[10px] text-[var(--muted)]">No satellites configured yet.</p>
              )}
            </div>
          </fieldset>

          <p className="text-[10px] text-[var(--muted)]">
            Navigation location = category tree. Execution location = UI slot. Independent.
            Install does not activate.
          </p>
          <button
            type="button"
            disabled={busy}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            onClick={() => void runInstall()}
            data-testid="wizard-install"
          >
            Step 4 — Install
          </button>
        </section>
      )}

      {step === 4 && (
        <section className="space-y-2 rounded border border-[var(--line)] p-3">
          <h4 className="flex items-center gap-1 text-xs font-semibold text-emerald-800">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Installed (inactive)
          </h4>
          <p className="text-[11px] text-[var(--muted)]">
            Placement {placementId || 'saved'}. Host images were not rebuilt.
          </p>
          <label className="flex items-center gap-2 text-[11px]">
            <input
              type="checkbox"
              checked={activateNow}
              onChange={(e) => setActivateNow(e.target.checked)}
              data-testid="wizard-activate-now"
            />
            Activate now (Step 5)
          </label>
          <button
            type="button"
            disabled={busy}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white"
            onClick={() => void runActivate()}
            data-testid="wizard-finish-activate"
          >
            {activateNow ? 'Activate & finish' : 'Finish without activating'}
          </button>
        </section>
      )}

      {step === 6 && (
        <section className="space-y-2 rounded border border-emerald-200 bg-emerald-50 p-3">
          <h4 className="text-xs font-semibold text-emerald-900">Step 6 — Manage</h4>
          <p className="text-[11px] text-emerald-900">
            Use Tool Tree Manager to move, reorder, upgrade, roll back, or disable. Uninstall is
            disable + remove placement.
          </p>
          <button
            type="button"
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white"
            onClick={onDone}
            data-testid="wizard-done"
          >
            Done
          </button>
        </section>
      )}
    </div>
  );
}
