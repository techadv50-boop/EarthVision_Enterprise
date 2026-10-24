import { RESOLUTION_BANDS } from '../../constants/imageryResolution';
import type { SatellitePublic } from '../../services/satelliteService';

interface ResolutionPickerProps {
  bands?: Array<{ key: string; label: string }>;
  selected: string[];
  onChange: (next: string[]) => void;
  required?: boolean;
}

interface SatellitePickerProps {
  satellites: SatellitePublic[];
  selected: string[];
  onChange: (next: string[]) => void;
}

/** Resolution bands from API when provided; otherwise static catalog. */
export function ResolutionApplicabilityPicker({
  bands,
  selected,
  onChange,
  required,
}: ResolutionPickerProps) {
  const options = bands?.length ? bands : RESOLUTION_BANDS;
  const allKeys = options.map((b) => b.key);
  const allOn = allKeys.length > 0 && allKeys.every((k) => selected.includes(k));

  function toggle(key: string) {
    onChange(
      selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key],
    );
  }

  return (
    <fieldset
      className="rounded border border-[var(--line)] p-2"
      data-testid="wizard-resolutions"
    >
      <legend className="px-1 text-[11px] font-semibold">
        Imagery resolutions this tool works with{required ? ' *' : ''}
      </legend>
      <p className="mb-1.5 text-[10px] text-[var(--muted)]">
        Select every resolution band this tool may run against. List comes from the platform
        resolution catalog (including bands added via API).
      </p>
      <div className="mb-1.5 flex flex-wrap gap-1.5">
        <button
          type="button"
          className="rounded border border-[var(--line)] px-2 py-0.5 text-[10px] font-semibold"
          onClick={() => onChange(allOn ? [] : [...allKeys])}
          data-testid="resolutions-select-all"
        >
          {allOn ? 'Clear all resolutions' : 'Select all resolutions'}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((band) => {
          const on = selected.includes(band.key);
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
                onChange={() => toggle(band.key)}
              />
              {band.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Satellites from admin API — includes providers added later via API. */
export function SatelliteApplicabilityPicker({
  satellites,
  selected,
  onChange,
}: SatellitePickerProps) {
  const allNames = satellites.map((s) => s.name);
  const allOn = allNames.length > 0 && allNames.every((n) => selected.includes(n));

  function toggle(name: string) {
    onChange(
      selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name],
    );
  }

  return (
    <fieldset
      className="rounded border border-[var(--line)] p-2"
      data-testid="wizard-satellites"
    >
      <legend className="px-1 text-[11px] font-semibold">
        Applicable satellites (optional)
      </legend>
      <p className="mb-1.5 text-[10px] text-[var(--muted)]">
        Leave empty to allow any satellite that matches the resolution tags. Or pick providers
        from the live satellite list (updates when satellites are added via API).
      </p>
      <div className="mb-1.5 flex flex-wrap gap-1.5">
        <button
          type="button"
          className="rounded border border-[var(--line)] px-2 py-0.5 text-[10px] font-semibold"
          disabled={!satellites.length}
          onClick={() => onChange(allOn ? [] : [...allNames])}
          data-testid="satellites-select-all"
        >
          {allOn ? 'Clear all satellites' : 'Select all satellites'}
        </button>
      </div>
      <div className="max-h-36 space-y-1 overflow-y-auto">
        {satellites.map((sat) => {
          const on = selected.includes(sat.name);
          return (
            <label
              key={sat.id}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-[var(--bg)]"
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => toggle(sat.name)}
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
  );
}
