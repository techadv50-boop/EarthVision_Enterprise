import { downloadCsv, fileStem } from '../predict/export';
import { satelliteType } from './catalog';
import type { WatchHit, WatchRelation } from './scan';

const RELATION_LABEL: Record<WatchRelation, string> = {
  overhead: 'Over the area',
  watching: 'Swath covers the area',
  'in-view': 'Above the horizon',
};

function locationLabel(lat: number, lon: number): string {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`;
}

/** Download every satellite currently listed for the selected area. */
export function exportOverheadCsv(areaName: string, hits: WatchHit[], checkedAt: Date) {
  const when = checkedAt.toISOString().replace(/\.\d{3}Z$/, 'Z');
  const headers = [
    'Satellite',
    'NORAD',
    'Constellation',
    'Type',
    'Relation',
    'Location',
    'Latitude',
    'Longitude',
    'Altitude km',
    'Swath km',
    'Distance from area km',
    'Elevation deg',
    'Area',
    'Time UTC',
  ];
  const rows = hits.map((hit) => [
    hit.name,
    hit.noradId == null ? '' : String(hit.noradId),
    hit.constellation,
    satelliteType(hit.name),
    RELATION_LABEL[hit.relation],
    locationLabel(hit.lat, hit.lon),
    hit.lat.toFixed(4),
    hit.lon.toFixed(4),
    Number.isFinite(hit.altKm) ? hit.altKm.toFixed(1) : '',
    hit.swathKm == null ? '' : String(hit.swathKm),
    hit.distanceKm < 1 ? '0' : hit.distanceKm.toFixed(1),
    Number.isFinite(hit.elevationDeg) ? hit.elevationDeg.toFixed(1) : '',
    areaName,
    when,
  ]);
  const title = `Who is overhead — ${areaName} — ${hits.length} satellites`;
  downloadCsv(`${fileStem(`overhead-${areaName}`, 'overhead')}.csv`, title, headers, rows);
}
