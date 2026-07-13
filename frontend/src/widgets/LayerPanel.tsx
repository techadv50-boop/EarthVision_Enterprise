import { X, Mountain, Map as MapIcon, Globe2 } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import type { GlobeController } from '../map/Globe';
import { OpenStreetMapImageryProvider } from 'cesium';
import { addRasterOverlay } from '../map/cesiumViewer';

interface Props {
  globe: GlobeController | null;
}

export function LayerPanel({ globe }: Props) {
  const {
    activePanel,
    setActivePanel,
    baseLayer,
    setBaseLayer,
    terrainEnabled,
    setTerrainEnabled,
    footprintsVisible,
    setFootprintsVisible,
  } = useMapStore();

  if (activePanel !== 'layers') return null;

  const applyBase = (layer: 'imagery' | 'osm' | 'terrain') => {
    setBaseLayer(layer);
    const viewer = globe?.getViewer();
    if (!viewer) return;
    viewer.imageryLayers.removeAll();
    if (layer === 'osm' || layer === 'imagery') {
      viewer.imageryLayers.addImageryProvider(
        new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }),
      );
    }
    if (layer === 'terrain') {
      viewer.imageryLayers.addImageryProvider(
        new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }),
      );
      const apiBase = import.meta.env.VITE_API_URL || '/api/v1';
      addRasterOverlay(viewer, 'demo-truecolor', apiBase);
    }
  };

  return (
    <aside className="pointer-events-auto absolute left-3 top-20 z-20 w-[min(100%-1.5rem,20rem)] animate-fade-up md:left-4">
      <div className="ev-panel p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">Layer Manager</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="ev-label">Base Maps</p>
        <div className="mb-4 grid grid-cols-3 gap-2">
          {(
            [
              ['imagery', MapIcon, 'Imagery'],
              ['osm', Globe2, 'OSM'],
              ['terrain', Mountain, 'EO Tile'],
            ] as const
          ).map(([id, Icon, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => applyBase(id)}
              className={`flex flex-col items-center gap-1 rounded-lg border px-2 py-3 text-[10px] ${
                baseLayer === id
                  ? 'border-orbit-500 bg-orbit-500/15 text-orbit-400'
                  : 'border-earth-700 text-earth-300 hover:bg-earth-800'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
        <label className="mb-2 flex items-center justify-between text-xs text-earth-200">
          <span>Terrain</span>
          <input
            type="checkbox"
            checked={terrainEnabled}
            onChange={(e) => setTerrainEnabled(e.target.checked)}
          />
        </label>
        <label className="flex items-center justify-between text-xs text-earth-200">
          <span>Scene Footprints</span>
          <input
            type="checkbox"
            checked={footprintsVisible}
            onChange={(e) => setFootprintsVisible(e.target.checked)}
          />
        </label>
      </div>
    </aside>
  );
}
