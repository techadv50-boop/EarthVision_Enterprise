import type { SatelliteKind } from './types';

/** Cartosat and SAR-series satellites shown in Track and Predict. */
export const PERMANENT_SATS: { name: string; norad: number; kind: SatelliteKind }[] = [
  { name: 'Cartosat-2B', norad: 36795, kind: 'optical' },
  { name: 'Cartosat-2C', norad: 41599, kind: 'optical' },
  { name: 'Cartosat-2D', norad: 41948, kind: 'optical' },
  { name: 'Cartosat-2E', norad: 42767, kind: 'optical' },
  { name: 'Cartosat-2F', norad: 43111, kind: 'optical' },
  { name: 'Cartosat-3', norad: 44804, kind: 'optical' },
  { name: 'EOS-8', norad: 60454, kind: 'optical' },
  { name: 'RISAT-2B', norad: 44233, kind: 'sar' },
  { name: 'RISAT-2BR1', norad: 44857, kind: 'sar' },
  { name: 'RISAT-2BR2', norad: 46905, kind: 'sar' },
  { name: 'RISAT-1A', norad: 51656, kind: 'sar' },
  { name: 'NISAR', norad: 65053, kind: 'sar' },
  { name: 'EOS-7', norad: 55562, kind: 'optical' },
  { name: 'OceanSat-3', norad: 54361, kind: 'optical' },
  { name: 'SARAL', norad: 39086, kind: 'sar' },
  { name: 'INSAT-3DR', norad: 41752, kind: 'optical' },
  { name: 'INSAT-3DS', norad: 58990, kind: 'optical' },
  { name: 'ResourceSat-2A', norad: 41877, kind: 'optical' },
  { name: 'HySIS', norad: 43719, kind: 'optical' },
];

const NAME_BY_NORAD = new Map(PERMANENT_SATS.map((sat) => [sat.norad, sat.name]));

/** Keep the series name when Celestrak publishes a generic catalog title. */
export function preferredSatName(norad: number | null | undefined, fallback: string): string {
  if (norad == null) return fallback;
  return NAME_BY_NORAD.get(norad) || fallback;
}
