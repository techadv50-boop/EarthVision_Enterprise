export interface SensorParams {
  /** Ground swath width in km. Used for area coverage. Default 60. */
  swathKm: number;
  /** Minimum elevation (deg) at a point target for AOS. Default 10. */
  minElevationDeg: number;
  // Reserved for later imaging modes without changing the Predict API:
  // fovDeg?: number;
  // offNadirDeg?: number;
  // imagingMode?: string;
}

export const DEFAULT_SENSOR: SensorParams = {
  swathKm: 60,
  minElevationDeg: 10,
};

export interface PredictSatellite {
  id: string;
  name: string;
  line1: string;
  line2: string;
  color: string;
  sensor?: Partial<SensorParams>;
}

export interface PredictTarget {
  kind: 'point' | 'area';
  name: string;
  /** WGS84 GeoJSON geometry (Point, Polygon, MultiPolygon, or GeometryCollection). */
  geometry: GeoJSON.Geometry;
  /** Representative point used for elevation / AOS (centroid for areas). */
  lon: number;
  lat: number;
}

export interface PassRow {
  passNumber: number;
  satelliteId: string;
  satelliteName: string;
  color: string;
  passDateUtc: string;
  startUtc: string;
  endUtc: string;
  durationSec: number;
  maxElevationDeg: number | null;
  maxElevationUtc: string | null;
  aosUtc: string;
  losUtc: string;
  visibility: string;
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

export interface SatelliteTrack {
  satelliteId: string;
  satelliteName: string;
  color: string;
  samples: TrackSample[];
  labels: TrackLabel[];
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
  sensor: SensorParams;
}
