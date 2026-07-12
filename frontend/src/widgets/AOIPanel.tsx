import { useEffect, useState } from 'react';
import { Pentagon, Save, Trash2, Navigation, Download, Upload } from 'lucide-react';
import { geoApi, rasterApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function coordsToKmlRing(ring: number[][]): string {
  return ring.map((c) => `${c[0]},${c[1]},0`).join(' ');
}

function geojsonToKml(collection: {
  type: string;
  features: Array<{
    type?: string;
    properties?: Record<string, unknown>;
    geometry?: { type: string; coordinates: unknown };
  }>;
}): string {
  const placemarks = collection.features
    .map((feature, i) => {
      const name = String(feature.properties?.name ?? `AOI ${i + 1}`);
      const geom = feature.geometry;
      if (!geom || geom.type !== 'Polygon') return '';
      const rings = geom.coordinates as number[][][];
      const outer = rings[0];
      if (!outer) return '';
      return `  <Placemark>
    <name>${name.replace(/[<>&]/g, '')}</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>${coordsToKmlRing(outer)}</coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>`;
    })
    .filter(Boolean)
    .join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>EarthVision AOIs</name>
${placemarks}
</Document>
</kml>`;
}

export default function AOIPanel() {
  const { aois, setAois, drawnGeometries, flyTo, renderAois, viewer } = useMapStore();
  const { showNotification } = useUIStore();
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);

  const loadAois = async () => {
    try {
      const { data } = await geoApi.aoi.list();
      setAois(data);
      renderAois(data);
    } catch {
      /* not authenticated or empty */
    }
  };

  useEffect(() => {
    void loadAois();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer]);

  const lastPolygon = [...drawnGeometries]
    .reverse()
    .find((f) => f.geometry.type === 'Polygon');

  const buildFeatureCollection = () => ({
    type: 'FeatureCollection' as const,
    features: aois
      .map((aoi) => {
        try {
          return JSON.parse(aoi.geojson);
        } catch {
          return null;
        }
      })
      .filter(Boolean),
  });

  const handleSave = async () => {
    if (!lastPolygon) {
      showNotification('Draw a polygon, rectangle, or circle first', 'error');
      return;
    }
    if (!name.trim()) {
      showNotification('Enter an AOI name', 'error');
      return;
    }
    setSaving(true);
    try {
      const geometryType =
        (lastPolygon.properties?.type as string) || lastPolygon.geometry.type;
      await geoApi.aoi.create({
        name: name.trim(),
        description: '',
        geometry_type: geometryType,
        geojson: JSON.stringify(lastPolygon),
      });
      setName('');
      showNotification('AOI saved', 'success');
      await loadAois();
    } catch {
      showNotification('Failed to save AOI', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await geoApi.aoi.delete(id);
      showNotification('AOI deleted', 'success');
      await loadAois();
    } catch {
      showNotification('Failed to delete AOI', 'error');
    }
  };

  const handleFlyTo = (geojson: string) => {
    try {
      const feature = JSON.parse(geojson);
      const coords =
        feature.geometry?.coordinates?.[0] || feature.coordinates?.[0];
      if (coords?.[0]) {
        const lons = coords.map((c: number[]) => c[0]);
        const lats = coords.map((c: number[]) => c[1]);
        const lon = (Math.min(...lons) + Math.max(...lons)) / 2;
        const lat = (Math.min(...lats) + Math.max(...lats)) / 2;
        flyTo(lon, lat, 50000);
      }
    } catch {
      showNotification('Invalid AOI geometry', 'error');
    }
  };

  const handleExportGeojson = () => {
    const collection = buildFeatureCollection();
    const blob = new Blob([JSON.stringify(collection, null, 2)], {
      type: 'application/geo+json',
    });
    downloadBlob(blob, 'earthvision-aois.geojson');
  };

  const handleExportKml = () => {
    const collection = buildFeatureCollection();
    const kml = geojsonToKml(collection);
    const blob = new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' });
    downloadBlob(blob, 'earthvision-aois.kml');
  };

  const handleExportShapefile = async () => {
    if (aois.length === 0) {
      showNotification('No AOIs to export', 'error');
      return;
    }
    try {
      const collection = buildFeatureCollection();
      const { data } = await rasterApi.exportShapefile(collection, 'earthvision-aois.zip');
      downloadBlob(data as Blob, 'earthvision-aois.zip');
      showNotification('Shapefile exported', 'success');
    } catch {
      showNotification('Shapefile export failed', 'error');
    }
  };

  const handleImport = async (file: File) => {
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const features =
        data.type === 'FeatureCollection'
          ? data.features
          : data.type === 'Feature'
            ? [data]
            : [];
      for (const feature of features) {
        await geoApi.aoi.create({
          name: feature.properties?.name || `Imported ${Date.now()}`,
          description: feature.properties?.description || '',
          geometry_type: feature.geometry?.type || 'Polygon',
          geojson: JSON.stringify(feature),
        });
      }
      showNotification(`Imported ${features.length} AOI(s)`, 'success');
      await loadAois();
    } catch {
      showNotification('GeoJSON import failed', 'error');
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <Pentagon className="w-4 h-4" /> Areas of Interest
      </h3>

      <div className="space-y-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="AOI name..."
          className="input-field text-sm"
        />
        <button
          onClick={handleSave}
          disabled={saving || !lastPolygon}
          className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
        >
          <Save className="w-4 h-4" />
          Save Last Drawing
        </button>
        {!lastPolygon && (
          <p className="text-xs text-gray-500">
            Draw a polygon, rectangle, or circle on the globe first.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={handleExportGeojson}
          className="btn-secondary text-xs flex items-center justify-center gap-1"
        >
          <Download className="w-3 h-3" /> GeoJSON
        </button>
        <button
          onClick={handleExportKml}
          className="btn-secondary text-xs flex items-center justify-center gap-1"
        >
          <Download className="w-3 h-3" /> KML
        </button>
        <button
          onClick={() => void handleExportShapefile()}
          className="btn-secondary text-xs flex items-center justify-center gap-1"
        >
          <Download className="w-3 h-3" /> Shapefile
        </button>
        <label className="btn-secondary text-xs flex items-center justify-center gap-1 cursor-pointer">
          <Upload className="w-3 h-3" /> Import
          <input
            type="file"
            accept=".geojson,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleImport(file);
            }}
          />
        </label>
      </div>

      <div className="max-h-56 overflow-y-auto space-y-1">
        {aois.map((aoi) => (
          <div
            key={aoi.id}
            className="flex items-center gap-2 p-2 rounded hover:bg-gray-800 group"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm truncate">{aoi.name}</div>
              <div className="text-xs text-gray-500">{aoi.geometry_type}</div>
            </div>
            <button
              onClick={() => handleFlyTo(aoi.geojson)}
              className="p-1 text-gray-500 hover:text-earth-400"
              title="Fly to"
            >
              <Navigation className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => void handleDelete(aoi.id)}
              className="p-1 text-gray-500 hover:text-red-400"
              title="Delete"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        {aois.length === 0 && (
          <p className="text-xs text-gray-500 text-center py-4">No saved AOIs</p>
        )}
      </div>
    </div>
  );
}
