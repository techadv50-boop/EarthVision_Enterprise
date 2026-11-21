import { canonicalizeTle } from '../tle';

const MU_KM3_S2 = 398600.4418;
const EARTH_KM = 6378.135;

export type Mission =
  | 'Optical imaging'
  | 'SAR imaging'
  | 'Communication'
  | 'Navigation'
  | 'Weather'
  | 'Reconnaissance'
  | 'Other';

export interface SatOrigin {
  country: string;
  operator: string;
}

export interface OrbitFacts {
  classification: 'Unclassified' | 'Classified' | 'Secret';
  designator: string;
  launchYear: number | null;
  inclinationDeg: number | null;
  eccentricity: number | null;
  periodMin: number | null;
  perigeeKm: number | null;
  apogeeKm: number | null;
  regime: string;
}

const COMMUNICATION_NAME =
  /starlink|oneweb|iridium|globalstar|orbcomm|intelsat|eutelsat|viasat|\bo3b\b|inmarsat|thuraya|telesat|\bses[- ]?\d|starone/i;
const NAVIGATION_NAME = /\bgps\b|navstar|glonass|galileo|beidou|\bqzss\b|irnss/i;
const RECON_NAME =
  /yaogan|\byg-\d|lacrosse|\bonyx\b|kh-11|kh-12|\bmisty\b|\bmentor\b|\borion\b|\btopaz\b|\bofeq\b|\bigs[- ]?\d|\busa[- ]?\d/i;
const SAR_NAME =
  /risat|iceye|capella|umbra|terrasar|radarsat|\bnisar\b|\bpaz\b|tandem|cosmo-skymed|gaofen-3|\bsar\b|sentinel[- ]?1|alos[- ]?2|\bsaral\b/i;
const WEATHER_NAME = /noaa|\bgoes\b|metop|fengyun|\bfy-\d|himawari|\bmeteo/i;
const IMAGING_NAME =
  /sentinel|landsat|cartosat|risat|resourcesat|oceansat|insat|gisat|hysis|nisar|worldview|geoeye|pleiades|\bspot\b|iceye|capella|umbra|terrasar|radarsat|alos|kompsat|gaofen|yaogan|jilin|skysat|planet|flock|noaa|goes|metop|fengyun|modis|prss|saral|\beos-|superview|blacksky|legion|cosmo-skymed|\bpaz\b|tandem/i;

const ORIGINS: [RegExp, string, string][] = [
  [/starlink/i, 'United States', 'SpaceX'],
  [/oneweb/i, 'United Kingdom', 'OneWeb'],
  [/iridium/i, 'United States', 'Iridium'],
  [/globalstar/i, 'United States', 'Globalstar'],
  [/orbcomm/i, 'United States', 'Orbcomm'],
  [/planet|flock|skysat|\bdove\b/i, 'United States', 'Planet'],
  [/sentinel/i, 'Europe', 'European Space Agency'],
  [/landsat/i, 'United States', 'NASA / USGS'],
  [/cartosat|risat|resourcesat|oceansat|\binsat\b|gisat|hysis|irnss/i, 'India', 'ISRO'],
  [/nisar/i, 'India and the United States', 'ISRO / NASA'],
  [/noaa|\bgoes\b/i, 'United States', 'NOAA'],
  [/metop/i, 'Europe', 'EUMETSAT'],
  [/fengyun|\bfy-\d|gaofen|\bgf-\d|yaogan|\byg-\d|jilin|beidou/i, 'China', 'China'],
  [/worldview|geoeye|legion/i, 'United States', 'Maxar'],
  [/pleiades|\bspot\b/i, 'France', 'Airbus'],
  [/iceye/i, 'Finland', 'ICEYE'],
  [/capella/i, 'United States', 'Capella'],
  [/umbra/i, 'United States', 'Umbra'],
  [/blacksky/i, 'United States', 'BlackSky'],
  [/terrasar|tandem/i, 'Germany', 'Germany'],
  [/radarsat/i, 'Canada', 'Canadian Space Agency'],
  [/alos|daichi|\bqzss\b|himawari/i, 'Japan', 'Japan'],
  [/kompsat/i, 'South Korea', 'South Korea'],
  [/cosmo-skymed/i, 'Italy', 'Italy'],
  [/\bpaz\b/i, 'Spain', 'Spain'],
  [/prss|paktes/i, 'Pakistan', 'SUPARCO'],
  [/\bgps\b|navstar|\busa[- ]?\d/i, 'United States', 'United States'],
  [/glonass|kosmos|cosmos/i, 'Russia', 'Russia'],
  [/galileo/i, 'Europe', 'European Union'],
  [/\biss\b|\bzarya\b/i, 'International', 'ISS partnership'],
  [/hubble|\bhst\b/i, 'United States', 'NASA'],
  [/intelsat/i, 'United States', 'Intelsat'],
  [/eutelsat/i, 'France', 'Eutelsat'],
  [/viasat/i, 'United States', 'Viasat'],
  [/inmarsat/i, 'United Kingdom', 'Inmarsat'],
  [/thuraya/i, 'United Arab Emirates', 'Thuraya'],
  [/telesat/i, 'Canada', 'Telesat'],
  [/\bses[- ]?\d|\bo3b\b/i, 'Luxembourg', 'SES'],
  [/ofeq/i, 'Israel', 'Israel'],
];

/** Optical, SAR, communication, navigation, weather, reconnaissance, or other. */
export function satelliteType(name: string): Mission {
  const n = name || '';
  if (COMMUNICATION_NAME.test(n)) return 'Communication';
  if (NAVIGATION_NAME.test(n)) return 'Navigation';
  if (RECON_NAME.test(n)) return 'Reconnaissance';
  if (SAR_NAME.test(n)) return 'SAR imaging';
  if (WEATHER_NAME.test(n)) return 'Weather';
  if (IMAGING_NAME.test(n)) return 'Optical imaging';
  return 'Other';
}

/** Country and operator when the satellite name belongs to a known program. */
export function originOf(name: string): SatOrigin | null {
  for (const [test, country, operator] of ORIGINS) {
    if (test.test(name)) return { country, operator };
  }
  return null;
}

function field(line: string, start: number, length: number): string {
  return line.length >= start + length ? line.slice(start, start + length).trim() : '';
}

function parseNum(raw: string): number | null {
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function regime(perigeeKm: number, apogeeKm: number, periodMin: number): string {
  if (apogeeKm >= 34000 && perigeeKm >= 34000) return 'Geostationary';
  if (apogeeKm >= 34000 && perigeeKm < 8000) return 'Highly elliptical';
  if (apogeeKm < 2000) return 'Low Earth orbit';
  if (periodMin >= 600 && periodMin <= 900) return 'Medium Earth orbit';
  if (perigeeKm > 2000 && apogeeKm < 34000) return 'Medium Earth orbit';
  return 'Other orbit';
}

/** Orbit, launch year, and catalog classification read from the two TLE lines. */
export function orbitFacts(line1: string, line2: string): OrbitFacts {
  const tle = canonicalizeTle(line1, line2);
  const first = tle.line1;
  const second = tle.line2;
  const mark = first.length > 7 ? first[7] : 'U';
  const classification = mark === 'S' ? 'Secret' : mark === 'C' ? 'Classified' : 'Unclassified';
  const intl = field(first, 9, 8);
  const yy = parseInt(intl.slice(0, 2), 10);
  const launchYear = intl.length >= 5 && Number.isFinite(yy) ? (yy >= 57 ? 1900 + yy : 2000 + yy) : null;
  const designator =
    launchYear != null ? `${launchYear}-${intl.slice(2, 5)}${intl.slice(5)}` : intl;
  const inclinationDeg = parseNum(field(second, 8, 8));
  const eccRaw = field(second, 26, 7);
  const eccentricity = eccRaw.includes('.') ? parseNum(eccRaw) : parseNum(eccRaw) == null ? null : Number(eccRaw) / 1e7;
  const motion = parseNum(field(second, 52, 11));
  let periodMin: number | null = null;
  let perigeeKm: number | null = null;
  let apogeeKm: number | null = null;
  if (motion != null && motion > 0 && eccentricity != null && eccentricity >= 0 && eccentricity < 1) {
    periodMin = 1440 / motion;
    const n = (motion * 2 * Math.PI) / 86400;
    const axis = Math.cbrt(MU_KM3_S2 / (n * n));
    perigeeKm = axis * (1 - eccentricity) - EARTH_KM;
    apogeeKm = axis * (1 + eccentricity) - EARTH_KM;
  }
  return {
    classification,
    designator,
    launchYear,
    inclinationDeg,
    eccentricity,
    periodMin,
    perigeeKm,
    apogeeKm,
    regime:
      perigeeKm != null && apogeeKm != null && periodMin != null
        ? regime(perigeeKm, apogeeKm, periodMin)
        : 'Other orbit',
  };
}

/** How long the satellite has been up, from its launch year. Active entries are still operating. */
export function yearsInOrbit(launchYear: number | null, now = new Date()): string {
  if (launchYear == null) return 'Still operating. The launch year is not in the element set.';
  const years = now.getUTCFullYear() - launchYear;
  if (years <= 0) return `Launched in ${launchYear}. Still operating.`;
  const word = years === 1 ? 'year' : 'years';
  return `Launched in ${launchYear}. About ${years} ${word} in orbit, and still operating.`;
}

export function formatPeriod(periodMin: number): string {
  const hours = Math.floor(periodMin / 60);
  const minutes = Math.round(periodMin % 60);
  if (hours <= 0) return `${periodMin.toFixed(1)} min`;
  return `${hours} h ${minutes} min`;
}
