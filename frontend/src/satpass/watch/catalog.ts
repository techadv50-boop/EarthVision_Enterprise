export interface ActiveSat {
  name: string;
  noradId: number | null;
  line1: string;
  line2: string;
}

const CONSTELLATIONS: [RegExp, string][] = [
  [/starlink/i, 'Starlink'],
  [/oneweb/i, 'OneWeb'],
  [/iridium/i, 'Iridium'],
  [/globalstar/i, 'Globalstar'],
  [/orbcomm/i, 'Orbcomm'],
  [/planet|flock|skysat|dove/i, 'Planet'],
  [/sentinel/i, 'Sentinel'],
  [/landsat/i, 'Landsat'],
  [/cartosat/i, 'Cartosat'],
  [/risat/i, 'RISAT'],
  [/resourcesat|\birs-/i, 'ResourceSat'],
  [/oceansat/i, 'OceanSat'],
  [/insat|gisat/i, 'INSAT'],
  [/hysis/i, 'HySIS'],
  [/nisar/i, 'NISAR'],
  [/noaa/i, 'NOAA'],
  [/goes/i, 'GOES'],
  [/metop/i, 'MetOp'],
  [/fengyun|\bfy-/i, 'Fengyun'],
  [/gaofen|\bgf-/i, 'Gaofen'],
  [/yaogan|\byg-/i, 'Yaogan'],
  [/jilin/i, 'Jilin'],
  [/worldview|geoeye|legion/i, 'Maxar'],
  [/pleiades/i, 'Pléiades'],
  [/\bspot\b/i, 'SPOT'],
  [/iceye/i, 'ICEYE'],
  [/capella/i, 'Capella'],
  [/umbra/i, 'Umbra'],
  [/terrasar|tandem|blacksky/i, 'SAR'],
  [/radarsat/i, 'RADARSAT'],
  [/alos|daichi/i, 'ALOS'],
  [/kompsat/i, 'KOMPSAT'],
  [/cosmo-skymed|\bpaz\b/i, 'COSMO-SkyMed'],
  [/prss/i, 'PRSS'],
  [/saral/i, 'SARAL'],
  [/\bgps\b|navstar/i, 'GPS'],
  [/glonass/i, 'GLONASS'],
  [/galileo/i, 'Galileo'],
  [/beidou/i, 'BeiDou'],
  [/iss\b|zarya/i, 'ISS'],
  [/hubble|\bhst\b/i, 'Hubble'],
];

const IMAGING_NAME =
  /sentinel|landsat|cartosat|risat|resourcesat|oceansat|insat|gisat|hysis|nisar|worldview|geoeye|pleiades|\bspot\b|iceye|capella|umbra|terrasar|radarsat|alos|kompsat|gaofen|yaogan|jilin|skysat|planet|flock|noaa|goes|metop|fengyun|modis|prss|saral|\beos-|superview|blacksky|legion|cosmo-skymed|\bpaz\b|tandem/i;

const SAR_NAME = /sar|risat|iceye|capella|umbra|terrasar|radarsat|yaogan|nisar|\bpaz\b|tandem|cosmo|gaofen-3/i;

export function constellationOf(name: string): string {
  for (const [test, label] of CONSTELLATIONS) {
    if (test.test(name)) return label;
  }
  const token = name.trim().split(/\s+/)[0];
  return token || 'Other';
}

/** Catalog swath, or a typical imaging swath when the name is an Earth-observation satellite. */
export function imagingSwathKm(name: string, catalogSwathKm: number | null): number | null {
  if (catalogSwathKm != null && catalogSwathKm > 0) return catalogSwathKm;
  if (!IMAGING_NAME.test(name)) return null;
  return SAR_NAME.test(name) ? 80 : 40;
}

export function parseTleCatalog(text: string): ActiveSat[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const sats: ActiveSat[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].startsWith('1 ') && i + 1 < lines.length && lines[i + 1].startsWith('2 ')) {
      const line1 = lines[i];
      sats.push({ name: `NORAD ${noradOf(line1) ?? ''}`.trim(), noradId: noradOf(line1), line1, line2: lines[i + 1] });
      i += 2;
      continue;
    }
    if (i + 2 < lines.length && lines[i + 1].startsWith('1 ') && lines[i + 2].startsWith('2 ')) {
      const line1 = lines[i + 1];
      sats.push({ name: lines[i], noradId: noradOf(line1), line1, line2: lines[i + 2] });
      i += 3;
      continue;
    }
    i += 1;
  }
  return sats;
}

function noradOf(line1: string): number | null {
  const n = parseInt(line1.slice(2, 7).trim(), 10);
  return Number.isFinite(n) ? n : null;
}

let cached: { at: number; sats: ActiveSat[] } | null = null;
const TTL_MS = 6 * 60 * 60 * 1000;

/** Current Celestrak active catalog. Cached in the browser for six hours. */
export async function loadActiveCatalog(force = false): Promise<ActiveSat[]> {
  if (!force && cached && Date.now() - cached.at < TTL_MS) return cached.sats;
  const resp = await fetch('/celestrak/NORAD/elements/gp.php?GROUP=active&FORMAT=TLE');
  if (!resp.ok) throw new Error(`Celestrak returned ${resp.status}`);
  const text = await resp.text();
  if (!text.trim() || text.includes('No GP data found')) {
    throw new Error('Celestrak returned no active satellites');
  }
  const sats = parseTleCatalog(text);
  if (!sats.length) throw new Error('Celestrak returned no usable TLEs');
  cached = { at: Date.now(), sats };
  return sats;
}
