/** Shared imagery resolution bands for tools and satellite admin tags. */

export interface ResolutionBand {
  key: string;
  label: string;
}

/** Canonical bands: ≤1m … ≤30m, <30m, and >30m for coarse sensors. */
export const RESOLUTION_BANDS: ResolutionBand[] = [
  { key: 'lte_1m', label: '≤1m' },
  { key: 'lte_2m', label: '≤2m' },
  { key: 'lte_3m', label: '≤3m' },
  { key: 'lte_5m', label: '≤5m' },
  { key: 'lte_10m', label: '≤10m' },
  { key: 'lte_15m', label: '≤15m' },
  { key: 'lte_30m', label: '≤30m' },
  { key: 'lt_30m', label: '<30m' },
  { key: 'gt_30m', label: '>30m' },
];

export function resolutionLabel(key: string | null | undefined): string {
  if (!key) return '—';
  return RESOLUTION_BANDS.find((b) => b.key === key)?.label || key;
}
