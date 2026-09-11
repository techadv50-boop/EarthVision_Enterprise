/**
 * Satellite metadata / configuration layer for Predict.
 *
 * Orbit math stays in passes.ts. This module owns type (Optical vs SAR),
 * colors, imaging eligibility rules, Pass IDs, and per-pass line styles so
 * the map renderer never hard-codes optical/SAR behavior.
 */
import type {
  ImagingRules,
  PassDash,
  PassRow,
  SatelliteKind,
  SensorParams,
} from './types';

export const PASS_DASHES: PassDash[] = ['solid', 'dashed', 'dotted'];

const NAMED_COLORS: { test: RegExp; color: string }[] = [
  { test: /cartosat[- ]?3/i, color: '#facc15' },
  { test: /\bprss\b/i, color: '#facc15' },
  { test: /landsat/i, color: '#22c55e' },
  { test: /sentinel[- ]?1/i, color: '#3b82f6' },
];

const AUTO_COLORS = [
  '#f97316',
  '#e879f9',
  '#fb7185',
  '#2dd4bf',
  '#a78bfa',
  '#34d399',
  '#ef4444',
  '#38bdf8',
  '#fbbf24',
];

export function colorForSatellite(name: string, used: Set<string>): string {
  for (const rule of NAMED_COLORS) {
    if (rule.test.test(name) && !used.has(rule.color)) return rule.color;
  }
  return AUTO_COLORS.find((c) => !used.has(c)) ?? AUTO_COLORS[used.size % AUTO_COLORS.length];
}

export function passDashForIndex(passNumber: number): PassDash {
  return PASS_DASHES[(Math.max(1, passNumber) - 1) % PASS_DASHES.length];
}

export function leafletDashArray(dash: PassDash): string | undefined {
  if (dash === 'dashed') return '10 7';
  if (dash === 'dotted') return '2 7';
  return undefined;
}

export function defaultImagingRules(kind: SatelliteKind): ImagingRules {
  return kind === 'optical'
    ? { requiresDaylight: true, minSolarElevationDeg: 0 }
    : { requiresDaylight: false, minSolarElevationDeg: -90 };
}

interface CatalogEntry {
  test: (name: string, norad: number | null) => boolean;
  kind: SatelliteKind;
  color?: string;
  sensor?: Partial<SensorParams>;
  slug?: string;
}

const S1_NORADS = new Set([39634, 41456, 58261]);
const CARTOSAT3_NORADS = new Set([44804]);

const CATALOG: CatalogEntry[] = [
  {
    test: (n) => /\bprss\b/i.test(n),
    kind: 'optical',
    color: '#facc15',
    sensor: { swathKm: 60, minElevationDeg: 20, spatialResolutionM: 1, maxOffNadirDeg: 30 },
    slug: 'PRSS',
  },
  {
    test: (n) => /landsat/i.test(n),
    kind: 'optical',
    color: '#22c55e',
    sensor: { swathKm: 185, minElevationDeg: 10, spatialResolutionM: 15 },
    slug: 'Landsat',
  },
  {
    test: (n, norad) => /sentinel[- ]?1/i.test(n) || (norad != null && S1_NORADS.has(norad)),
    kind: 'sar',
    color: '#3b82f6',
    sensor: { swathKm: 250, minElevationDeg: 10 },
    slug: 'Sentinel-1',
  },
  {
    test: (n) => /sentinel[- ]?2/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 290, minElevationDeg: 10, spatialResolutionM: 10 },
    slug: 'Sentinel-2',
  },
  {
    test: (n, norad) => /cartosat[- ]?3/i.test(n) || (norad != null && CARTOSAT3_NORADS.has(norad)),
    kind: 'optical',
    color: '#facc15',
    sensor: { swathKm: 17, minElevationDeg: 20, maxOffNadirDeg: 45, spatialResolutionM: 0.28 },
    slug: 'CARTOSAT-3',
  },
  {
    test: (n) => /cartosat[- ]?2[cdef]/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 10, minElevationDeg: 20, spatialResolutionM: 0.65 },
    slug: 'CARTOSAT-2',
  },
  {
    test: (n) => /cartosat[- ]?2/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 9.6, minElevationDeg: 20, spatialResolutionM: 0.8 },
    slug: 'CARTOSAT-2',
  },
  {
    test: (n) => /cartosat[- ]?1/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 30, minElevationDeg: 20, spatialResolutionM: 2.5 },
    slug: 'CARTOSAT-1',
  },
  {
    test: (n) => /cartosat/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 16, minElevationDeg: 20, spatialResolutionM: 0.8 },
    slug: 'CARTOSAT',
  },
  {
    test: (n) => /worldview[- ]?3/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 13.1, minElevationDeg: 20, maxOffNadirDeg: 40, spatialResolutionM: 0.31 },
  },
  {
    test: (n) => /worldview[- ]?2/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 16.4, minElevationDeg: 20, spatialResolutionM: 0.46 },
  },
  {
    test: (n) => /geoeye/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 15.2, minElevationDeg: 20, spatialResolutionM: 0.41 },
  },
  {
    test: (n) => /pleiades/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 20, minElevationDeg: 20, spatialResolutionM: 0.5 },
  },
  {
    test: (n) => /spot[- ]?[67]/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 60, minElevationDeg: 20, spatialResolutionM: 1.5 },
  },
  {
    test: (n) => /kompsat[- ]?3/i.test(n),
    kind: 'optical',
    sensor: { swathKm: 16, minElevationDeg: 20, spatialResolutionM: 0.5 },
  },
  {
    test: (n) => /radarsat|alos[- ]?2|cosmo[- ]?skymed|iceye|capella|umbra|risat|\bsar\b/i.test(n),
    kind: 'sar',
    color: '#3b82f6',
    sensor: { swathKm: 50, minElevationDeg: 10 },
  },
  {
    test: (n) =>
      /worldview|geoeye|pleiades|spot[- ]?\d|kompsat|gaofen|superview|skysat|planet|terra\b|aqua\b|modis|noaa/i.test(
        n,
      ),
    kind: 'optical',
    sensor: { swathKm: 20, minElevationDeg: 20 },
  },
];

export function describeSensor(sensor: Partial<SensorParams> | undefined): string {
  if (!sensor?.swathKm) return '';
  const bits = [`${sensor.swathKm} km swath`];
  if (sensor.minElevationDeg != null) bits.push(`min el ${sensor.minElevationDeg}°`);
  if (sensor.spatialResolutionM != null) {
    const r = sensor.spatialResolutionM;
    bits.push(r < 1 ? `${r} m GSD` : `${r} m`);
  }
  return bits.join(' · ');
}

export function inferSatelliteKind(name: string, norad: number | null): SatelliteKind {
  for (const entry of CATALOG) {
    if (entry.test(name, norad)) return entry.kind;
  }
  return 'optical';
}

export function catalogSensor(name: string, norad: number | null): Partial<SensorParams> {
  for (const entry of CATALOG) {
    if (entry.test(name, norad) && entry.sensor) return entry.sensor;
  }
  return {};
}

/** Complete imaging parameters, or null if this satellite is not in the catalog. */
export function knownSensor(name: string, norad: number | null): SensorParams | null {
  const s = catalogSensor(name, norad);
  if (s.swathKm == null || s.minElevationDeg == null) return null;
  return {
    swathKm: s.swathKm,
    minElevationDeg: s.minElevationDeg,
    maxOffNadirDeg: s.maxOffNadirDeg,
    fovDeg: s.fovDeg,
    spatialResolutionM: s.spatialResolutionM,
    lookDirection: s.lookDirection,
  };
}

export function catalogColor(name: string): string | undefined {
  for (const entry of CATALOG) {
    if (entry.test(name, null) && entry.color) return entry.color;
  }
  return undefined;
}

export function noradFromLine1(line1: string): number | null {
  const n = parseInt(line1.slice(2, 7).trim(), 10);
  return Number.isFinite(n) ? n : null;
}

export function passSlug(name: string): string {
  for (const entry of CATALOG) {
    if (entry.slug && entry.test(name, null)) return entry.slug;
  }
  const cleaned = name
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^A-Za-z0-9.-]/g, '');
  return (cleaned || 'SAT').slice(0, 18);
}

export function makePassId(name: string, passNumber: number, _dateUtc?: string): string {
  return `${passSlug(name)}-P${String(passNumber).padStart(3, '0')}`;
}

export function resolveImagingRules(
  kind: SatelliteKind,
  override?: Partial<ImagingRules>,
): ImagingRules {
  return { ...defaultImagingRules(kind), ...override };
}

export function resolveSensor(
  name: string,
  norad: number | null,
  satOverride?: Partial<SensorParams>,
  fallback?: SensorParams,
): { sensor: SensorParams; source: 'catalog' | 'fallback' } | null {
  const known = knownSensor(name, norad);
  if (known) {
    return { sensor: { ...known, ...satOverride }, source: 'catalog' };
  }
  if (fallback && satOverride?.swathKm != null && satOverride?.minElevationDeg != null) {
    return { sensor: { ...fallback, ...satOverride }, source: 'fallback' };
  }
  if (fallback) return { sensor: fallback, source: 'fallback' };
  return null;
}

export function isImagingSample(kind: SatelliteKind, rules: ImagingRules, sunElevationDeg: number): boolean {
  if (!rules.requiresDaylight) return true;
  return sunElevationDeg >= rules.minSolarElevationDeg;
}

export function classifyDayNight(sunElevationDeg: number, lon: number, date: Date): PassRow['visibility'] {
  if (sunElevationDeg > 0) return 'daylight';
  if (sunElevationDeg > -6) {
    const utcHours = date.getUTCHours() + date.getUTCMinutes() / 60;
    const solar = (utcHours + lon / 15 + 24) % 24;
    return solar < 12 ? 'dawn' : 'dusk';
  }
  return 'night';
}

export function imagingStatusLabel(kind: SatelliteKind, visibility: PassRow['visibility'], eligible: boolean): string {
  const vis =
    visibility === 'daylight'
      ? 'Daylight'
      : visibility === 'night'
        ? 'Night'
        : visibility === 'dawn'
          ? 'Dawn'
          : visibility === 'dusk'
            ? 'Dusk'
            : 'Mixed';
  const kindLabel = kind === 'sar' ? 'SAR' : 'Optical';
  return eligible ? `${vis} / ${kindLabel} imaging eligible` : `${vis} / not eligible`;
}

export function formatPassPopup(pass: PassRow, timeZone: string, fmt: {
  zone: (iso: string, tz: string) => string;
  utc: (iso: string) => string;
  duration: (sec: number) => string;
}): string {
  const maxEl = pass.maxElevationDeg == null ? '—' : `${pass.maxElevationDeg.toFixed(1)}°`;
  const maxElT = pass.maxElevationUtc ? `${fmt.zone(pass.maxElevationUtc, timeZone)}<br>${fmt.utc(pass.maxElevationUtc)}` : '—';
  const minReq = pass.minElevationDeg == null ? '—' : `${pass.minElevationDeg}°`;
  const swath = pass.swathKm == null ? '—' : `${pass.swathKm} km`;
  return `
    <div style="min-width:220px;font:12px Inter,sans-serif;line-height:1.45">
      <div><b>Satellite:</b> ${escapeHtml(pass.satelliteName)}</div>
      <div><b>Type:</b> ${pass.satelliteKind === 'sar' ? 'SAR' : 'Optical'}</div>
      <div><b>Pass ID:</b> ${escapeHtml(pass.passId)}</div>
      <div><b>Target:</b> ${escapeHtml(pass.targetName)}</div>
      <div><b>Date:</b> ${escapeHtml(pass.passDateUtc)}</div>
      <div><b>Start tracking:</b> ${fmt.utc(pass.startUtc)}<br>${fmt.zone(pass.startUtc, timeZone)}</div>
      <div><b>End tracking:</b> ${fmt.utc(pass.endUtc)}<br>${fmt.zone(pass.endUtc, timeZone)}</div>
      <div><b>Duration:</b> ${fmt.duration(pass.durationSec)}</div>
      <div><b>Maximum elevation:</b> ${maxEl}</div>
      <div><b>Max elevation time:</b> ${maxElT}</div>
      <div><b>Min required elevation:</b> ${minReq}</div>
      <div><b>Swath:</b> ${swath}</div>
      <div><b>Day/Night:</b> ${pass.visibility}</div>
      <div><b>Imaging eligibility:</b> ${escapeHtml(pass.imagingStatus)}</div>
    </div>
  `;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}
