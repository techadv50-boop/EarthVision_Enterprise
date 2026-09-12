export type SatelliteKind = 'optical' | 'sar';
export type PassDash = 'solid' | 'dashed' | 'dotted';
export type DayNightStatus = 'daylight' | 'night' | 'dawn' | 'dusk' | 'mixed';

export interface ImagingRules {
  /** Optical imaging requires solar illumination of the target. SAR does not. */
  requiresDaylight: boolean;
  /** Minimum solar elevation (deg) at the target for optical imaging. Default 0 (sun above horizon). */
  minSolarElevationDeg: number;
}

export interface SensorParams {
  /** Ground swath width in km. Used for area coverage and pass footprints. */
  swathKm: number;
  /** Minimum elevation (deg) at the target for a usable imaging pass. */
  minElevationDeg: number;
  /** Published max off-nadir / body-pointing angle (deg), when known. */
  maxOffNadirDeg?: number;
  // Reserved for later imaging modes without changing the Predict API:
  fovDeg?: number;
  offNadirDeg?: number;
  imagingMode?: string;
  spatialResolutionM?: number;
  incidenceMinDeg?: number;
  incidenceMaxDeg?: number;
  lookDirection?: 'left' | 'right' | 'both';
}

export const DEFAULT_SENSOR: SensorParams = {
  swathKm: 60,
  minElevationDeg: 10,
};

export interface PredictTarget {
  kind: 'point' | 'area';
  name: string;
  /** WGS84 GeoJSON geometry (Point, Polygon, MultiPolygon, or GeometryCollection). */
  geometry: GeoJSON.Geometry;
  /** Representative point used for elevation / AOS (centroid for areas). */
  lon: number;
  lat: number;
  /** Geodesic buffer applied around a place/point, if any. */
  bufferKm?: number;
  source?: 'place' | 'coordinates' | 'upload';
}

export type SensorSource = 'catalog' | 'fallback' | 'none';

export interface PredictSatellite {
  id: string;
  name: string;
  line1: string;
  line2: string;
  color: string;
  kind: SatelliteKind;
  noradId?: number | null;
  sensor?: Partial<SensorParams>;
  imaging?: Partial<ImagingRules>;
  paramsKnown?: boolean;
  sensorSource?: SensorSource;
}

export interface PassRow {
  passId: string;
  passNumber: number;
  satelliteId: string;
  satelliteName: string;
  satelliteKind: SatelliteKind;
  noradId: number | null;
  color: string;
  dash: PassDash;
  passDateUtc: string;
  startUtc: string;
  endUtc: string;
  durationSec: number;
  maxElevationDeg: number | null;
  maxElevationUtc: string | null;
  aosUtc: string;
  losUtc: string;
  visibility: DayNightStatus;
  imagingEligible: boolean;
  imagingStatus: string;
  targetName: string;
  minElevationDeg: number | null;
  swathKm: number | null;
  sensorSource?: SensorSource;
}

export interface TrackLabel {
  utcMs: number;
  lat: number;
  lon: number;
  text: string;
}

export interface TrackSample {
  utcMs: number;
  lat: number;
  lon: number;
}

/** One independent imaging pass: track, labels, and footprint corridor. */
export interface SatelliteTrack {
  passId: string;
  satelliteId: string;
  satelliteName: string;
  satelliteKind: SatelliteKind;
  color: string;
  dash: PassDash;
  samples: TrackSample[];
  labels: TrackLabel[];
  footprint: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
}

export interface PredictResult {
  warnings: string[];
  passes: PassRow[];
  tracks: SatelliteTrack[];
}

export interface ComputeOptions {
  startUtc: Date;
  endUtc: Date;
  timeZone: string;
  labelIntervalMin: 1 | 2 | 5 | 10;
  /** Emergency fallback for satellites with no catalog parameters. */
  fallbackSensor?: SensorParams;
  allowFallback?: boolean;
}
