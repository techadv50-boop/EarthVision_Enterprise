declare namespace GeoJSON {
  type Position = number[];

  interface Geometry {
    type: string;
    coordinates: any;
  }

  interface Point {
    type: 'Point';
    coordinates: Position;
  }

  interface LineString {
    type: 'LineString';
    coordinates: Position[];
  }

  interface Polygon {
    type: 'Polygon';
    coordinates: Position[][];
  }

  interface MultiPolygon {
    type: 'MultiPolygon';
    coordinates: Position[][][];
  }

  interface Feature<G extends Geometry | null = Geometry, P = Record<string, unknown> | null> {
    type: 'Feature';
    geometry: G;
    properties: P;
    id?: string | number;
  }

  interface FeatureCollection<G extends Geometry | null = Geometry> {
    type: 'FeatureCollection';
    features: Feature<G>[];
  }
}
