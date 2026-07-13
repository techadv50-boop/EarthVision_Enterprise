import { useEffect, useRef } from 'react';
import { Circle, Download, Pentagon, Square, Trash2, Upload, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import { createDrawingController, type DrawingController } from '../map/drawing';
import { gisService } from '../services/gisService';
import type { GlobeController } from '../map/Globe';

interface Props {
  globe: GlobeController | null;
}

export function AoiPanel({ globe }: Props) {
  const {
    activePanel,
    setActivePanel,
    drawMode,
    setDrawMode,
    aoiGeoJson,
    setAoi,
    setMeasurementLabel,
  } = useMapStore();
  const drawingRef = useRef<DrawingController | null>(null);

  useEffect(() => {
    const handles = globe?.getHandles();
    if (!handles) return;
    drawingRef.current = createDrawingController(handles.viewer, handles.aoi, async (feature) => {
      setAoi(feature);
      setDrawMode('none');
      try {
        const measure = await gisService.measure(feature.geometry, 'kilometers');
        setMeasurementLabel(measure.display_value);
      } catch {
        setMeasurementLabel(null);
      }
    });
    return () => {
      drawingRef.current?.destroy();
      drawingRef.current = null;
    };
  }, [globe, setAoi, setDrawMode, setMeasurementLabel]);

  useEffect(() => {
    drawingRef.current?.setMode(drawMode);
  }, [drawMode]);

  if (activePanel !== 'aoi') return null;

  const start = (mode: typeof drawMode) => {
    setDrawMode(mode);
  };

  const clear = () => {
    drawingRef.current?.clear();
    setAoi(null);
    setMeasurementLabel(null);
    setDrawMode('none');
  };

  const exportGeoJson = async () => {
    if (!aoiGeoJson) return;
    const fc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: [aoiGeoJson],
    };
    const blob = await gisService.exportFeatures(fc, 'geojson');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'aoi.geojson';
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportKml = async () => {
    if (!aoiGeoJson) return;
    const fc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: [aoiGeoJson],
    };
    const blob = await gisService.exportFeatures(fc, 'kml');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'aoi.kml';
    a.click();
    URL.revokeObjectURL(url);
  };

  const importFile = async (file: File) => {
    const text = await file.text();
    if (file.name.endsWith('.kml') || text.includes('<kml')) {
      // Minimal KML polygon parse
      const match = text.match(/<coordinates>([^<]+)<\/coordinates>/);
      if (match) {
        const coords = match[1]
          .trim()
          .split(/\s+/)
          .map((c) => {
            const [lon, lat] = c.split(',').map(Number);
            return [lon, lat] as [number, number];
          });
        if (coords.length >= 3) {
          setAoi({
            type: 'Feature',
            properties: { name: file.name, kind: 'imported' },
            geometry: { type: 'Polygon', coordinates: [coords] },
          });
        }
      }
      return;
    }
    const geo = JSON.parse(text);
    if (geo.type === 'Feature') setAoi(geo);
    else if (geo.type === 'FeatureCollection' && geo.features?.[0]) setAoi(geo.features[0]);
    else if (geo.type === 'Polygon') {
      setAoi({ type: 'Feature', properties: {}, geometry: geo });
    }
  };

  return (
    <aside className="pointer-events-auto absolute left-3 top-20 z-20 w-[min(100%-1.5rem,20rem)] animate-fade-up md:left-4">
      <div className="ev-panel p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">AOI Drawing</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <button type="button" className={`ev-btn-secondary flex-col py-3 ${drawMode === 'polygon' ? 'ring-1 ring-orbit-500' : ''}`} onClick={() => start('polygon')}>
            <Pentagon className="h-4 w-4" />
            <span className="text-[10px]">Polygon</span>
          </button>
          <button type="button" className={`ev-btn-secondary flex-col py-3 ${drawMode === 'rectangle' ? 'ring-1 ring-orbit-500' : ''}`} onClick={() => start('rectangle')}>
            <Square className="h-4 w-4" />
            <span className="text-[10px]">Rectangle</span>
          </button>
          <button type="button" className={`ev-btn-secondary flex-col py-3 ${drawMode === 'circle' ? 'ring-1 ring-orbit-500' : ''}`} onClick={() => start('circle')}>
            <Circle className="h-4 w-4" />
            <span className="text-[10px]">Circle</span>
          </button>
        </div>
        <p className="mt-2 text-[11px] text-earth-400">
          Polygon: click vertices, double-click to finish. Rectangle/Circle: click two points.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="ev-btn-secondary text-xs" onClick={clear}>
            <Trash2 className="h-3.5 w-3.5" /> Clear
          </button>
          <button type="button" className="ev-btn-secondary text-xs" disabled={!aoiGeoJson} onClick={exportGeoJson}>
            <Download className="h-3.5 w-3.5" /> GeoJSON
          </button>
          <button type="button" className="ev-btn-secondary text-xs" disabled={!aoiGeoJson} onClick={exportKml}>
            <Download className="h-3.5 w-3.5" /> KML
          </button>
          <label className="ev-btn-secondary cursor-pointer text-xs">
            <Upload className="h-3.5 w-3.5" /> Import
            <input
              type="file"
              accept=".geojson,.json,.kml"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importFile(f);
              }}
            />
          </label>
        </div>
        {aoiGeoJson && (
          <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-earth-950/70 p-2 text-[10px] text-earth-400">
            {JSON.stringify(aoiGeoJson.geometry, null, 2)}
          </pre>
        )}
      </div>
    </aside>
  );
}
