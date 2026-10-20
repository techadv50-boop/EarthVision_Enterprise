/**
 * OSINT-style true-color band recipes (USGS / ESA / Esri composites).
 * Mirrors backend COMPOSITE_BAND_CODES["true_color"].
 */

export type TrueColorBandRecipe = {
  family: string;
  codes: string;
  formula: string;
  R: string;
  G: string;
  B: string;
};

const TRUE_COLOR_BY_FAMILY: Record<string, Omit<TrueColorBandRecipe, 'family'>> = {
  'SENTINEL-2': {
    codes: 'B04-B03-B02',
    formula: 'R=Red(B04), G=Green(B03), B=Blue(B02) — natural color',
    R: 'B04',
    G: 'B03',
    B: 'B02',
  },
  'LANDSAT-8': {
    codes: 'B4-B3-B2',
    formula: 'R=Red(B4), G=Green(B3), B=Blue(B2) — natural color',
    R: 'B4',
    G: 'B3',
    B: 'B2',
  },
  'LANDSAT-9': {
    codes: 'B4-B3-B2',
    formula: 'R=Red(B4), G=Green(B3), B=Blue(B2) — natural color',
    R: 'B4',
    G: 'B3',
    B: 'B2',
  },
  'LANDSAT-7': {
    codes: 'B3-B2-B1',
    formula: 'R=Red(B3), G=Green(B2), B=Blue(B1) — natural color',
    R: 'B3',
    G: 'B2',
    B: 'B1',
  },
  MODIS: {
    codes: 'B01-B04-B03',
    formula: 'R=Red(B01), G=Green(B04), B=Blue(B03) — natural color',
    R: 'B01',
    G: 'B04',
    B: 'B03',
  },
};

export function normalizeSatelliteFamily(collection?: string | null): string {
  const c = (collection || '').toUpperCase().replace(/_/g, '-');
  if (!c) return 'UNKNOWN';
  if (c.startsWith('S2') || c.includes('SENTINEL-2')) return 'SENTINEL-2';
  if (c.startsWith('S1') || c.includes('SENTINEL-1')) return 'SENTINEL-1';
  if (c.includes('SENTINEL-3') || c === 'S3' || c === 'OLCI' || c === 'SLSTR' || c.startsWith('S3-')) {
    return 'SENTINEL-3';
  }
  if (c.includes('SENTINEL-5') || c.includes('S5P')) return 'SENTINEL-5P';
  if (c.includes('LANDSAT-8') || c === 'LC08' || c === 'L8') return 'LANDSAT-8';
  if (c.includes('LANDSAT-9') || c === 'LC09' || c === 'L9') return 'LANDSAT-9';
  if (c.includes('LANDSAT-7') || c === 'LE07' || c === 'L7') return 'LANDSAT-7';
  if (c.includes('LANDSAT')) return 'LANDSAT-8';
  if (c === 'MODIS' || c.includes('MODIS') || c === 'TERRA' || c === 'AQUA') return 'MODIS';
  if (c.includes('SMOS')) return 'SMOS';
  return c;
}

/** Optical Image Processing block reason (SAR / atmosphere / microwave). */
export function opticalProcessingBlockReason(collection?: string | null): string | null {
  const family = normalizeSatelliteFamily(collection);
  if (family === 'SENTINEL-1') {
    return 'Sentinel-1 SAR does not support optical Image Processing tools. Use Sentinel-2 or Landsat.';
  }
  if (family === 'SENTINEL-3') {
    return 'Sentinel-3 is not wired for land optical composites in this app. Use Sentinel-2 or Landsat.';
  }
  if (family === 'SENTINEL-5P') {
    return 'Sentinel-5P atmospheric products do not support land optical Image Processing tools.';
  }
  if (family === 'SMOS') {
    return 'SMOS does not support optical Image Processing tools. Use Sentinel-2 or Landsat.';
  }
  if (!(family in TRUE_COLOR_BY_FAMILY)) {
    if (!collection) return 'Select an optical satellite scene first.';
    return `True color is not available for ${family}. Use Sentinel-2, Landsat, or MODIS.`;
  }
  return null;
}

export function trueColorBandRecipe(collection?: string | null): TrueColorBandRecipe | null {
  const family = normalizeSatelliteFamily(collection);
  const recipe = TRUE_COLOR_BY_FAMILY[family];
  if (!recipe) return null;
  return { family, ...recipe };
}
