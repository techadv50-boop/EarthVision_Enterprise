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

/** Celestrak refuses a second GROUP=active download from the same server for about two hours. */
export function isCelestrakStub(text: string): boolean {
  return /has not updated since your last successful/i.test(text) || text.includes('No GP data found');
}

type CatalogSource = 'live' | 'saved';

let memory: { at: number; sats: ActiveSat[]; source: CatalogSource } | null = null;
let inflight: Promise<ActiveSat[]> | null = null;
let sourceNote = '';

const LIVE_TTL_MS = 6 * 60 * 60 * 1000;
const SAVED_TTL_MS = 10 * 60 * 1000;
const IDB_MAX_AGE_MS = 36 * 60 * 60 * 1000;
/** When this copy of the app was built, the bundled catalog was current. */
const SNAPSHOT_AT = Date.parse('2026-10-27T01:46:00Z');

export function catalogSourceNote(): string {
  return sourceNote;
}

function remember(sats: ActiveSat[], source: CatalogSource) {
  memory = { at: Date.now(), sats, source };
  sourceNote =
    source === 'saved'
      ? 'Using the saved active catalog. Celestrak is limiting a fresh download from this server.'
      : '';
}

function idb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null);
      return;
    }
    const req = indexedDB.open('satpass-watch', 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains('catalog')) req.result.createObjectStore('catalog');
    };
    req.onerror = () => resolve(null);
    req.onsuccess = () => resolve(req.result);
  });
}

async function saveIdb(text: string): Promise<void> {
  try {
    const db = await idb();
    if (!db) return;
    await new Promise<void>((resolve) => {
      const tx = db.transaction('catalog', 'readwrite');
      tx.objectStore('catalog').put({ at: Date.now(), text }, 'active');
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // A saved copy is optional. The live list is already in memory.
  }
}

async function readIdb(): Promise<{ at: number; text: string } | null> {
  try {
    const db = await idb();
    if (!db) return null;
    return await new Promise((resolve) => {
      const tx = db.transaction('catalog', 'readonly');
      const req = tx.objectStore('catalog').get('active');
      req.onsuccess = () => {
        const row = req.result as { at?: number; text?: string } | undefined;
        if (!row || typeof row.text !== 'string' || typeof row.at !== 'number') resolve(null);
        else if (Date.now() - row.at > IDB_MAX_AGE_MS) resolve(null);
        else resolve({ at: row.at, text: row.text });
      };
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function readSnapshot(): Promise<ActiveSat[] | null> {
  if (typeof DecompressionStream === 'undefined') return null;
  try {
    const resp = await fetch('/catalog/active.tle.gz');
    if (!resp.ok || !resp.body) return null;
    const text = await new Response(resp.body.pipeThrough(new DecompressionStream('gzip'))).text();
    if (!text.trim() || isCelestrakStub(text)) return null;
    const sats = parseTleCatalog(text);
    return sats.length ? sats : null;
  } catch {
    return null;
  }
}

async function readSaved(): Promise<ActiveSat[] | null> {
  const row = await readIdb();
  let best: { at: number; sats: ActiveSat[] } | null = null;
  if (row && !isCelestrakStub(row.text)) {
    const sats = parseTleCatalog(row.text);
    if (sats.length) best = { at: row.at, sats };
  }
  if (!best || best.at < SNAPSHOT_AT) {
    const snap = await readSnapshot();
    if (snap) best = { at: SNAPSHOT_AT, sats: snap };
  }
  return best?.sats ?? null;
}

async function fetchCatalog(): Promise<ActiveSat[]> {
  let failure = 'Could not load the active catalog';
  try {
    const resp = await fetch('/celestrak/NORAD/elements/gp.php?GROUP=active&FORMAT=TLE');
    const text = await resp.text();
    if (!resp.ok || isCelestrakStub(text)) {
      failure = isCelestrakStub(text)
        ? 'Celestrak asked this server to wait before downloading the active catalog again'
        : `Celestrak returned ${resp.status}`;
      throw new Error(failure);
    }
    const sats = parseTleCatalog(text);
    if (!sats.length) throw new Error('Celestrak returned no usable TLEs');
    remember(sats, 'live');
    void saveIdb(text);
    return sats;
  } catch (err) {
    const saved = await readSaved();
    if (saved) {
      remember(saved, 'saved');
      return saved;
    }
    throw err instanceof Error ? err : new Error(failure);
  }
}

/**
 * Current Celestrak active catalog.
 * One download is shared by the whole page. A repeat download is refused by
 * Celestrak, so a refusal falls back to the last good copy.
 */
export function loadActiveCatalog(force = false): Promise<ActiveSat[]> {
  const ttl = memory?.source === 'live' ? LIVE_TTL_MS : SAVED_TTL_MS;
  if (!force && memory && Date.now() - memory.at < ttl) return Promise.resolve(memory.sats);
  if (!force && inflight) return inflight;
  let run: Promise<ActiveSat[]>;
  run = fetchCatalog().finally(() => {
    if (inflight === run) inflight = null;
  });
  inflight = run;
  return run;
}
