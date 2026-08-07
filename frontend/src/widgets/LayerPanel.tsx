import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, Layers, Mountain, Map, Upload } from 'lucide-react';
import * as Cesium from 'cesium';
import { offlineApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

interface OfflineLayer {
  id: string;
  name: string;
  category: string;
  type: string;
  subtype?: string;
  description: string;
  url_template?: string;
  path?: string;
  enabled_default?: boolean;
}

const VECTOR_PROP = 'sateyeVectorLayer';

export default function LayerPanel() {
  const [layers, setLayers] = useState<OfflineLayer[]>([]);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [basemapStyle, setBasemapStyle] = useState('satellite');
  const elevRef = useRef<HTMLInputElement>(null);
  const vecRef = useRef<HTMLInputElement>(null);
  const { viewer, layerVisibility, toggleLayer, addAnalysisLayer } = useMapStore();
  const { showNotification } = useUIStore();
  const vectorEntities = useRef<Record<string, string[]>>({});

  useEffect(() => {
    void offlineApi.layers().then(({ data }) => {
      const list = (data.layers || []) as OfflineLayer[];
      setLayers(list);
      const init: Record<string, boolean> = {};
      for (const layer of list) {
        init[layer.id] = Boolean(layer.enabled_default);
      }
      setEnabled(init);
    });
  }, []);

  // Apply default vector layers when viewer ready
  useEffect(() => {
    if (!viewer) return;
    for (const [id, on] of Object.entries(enabled)) {
      if (on) void ensureLayer(id, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer]);

  const removeVector = (layerId: string) => {
    if (!viewer) return;
    const ids = vectorEntities.current[layerId] || [];
    for (const eid of ids) {
      const ent = viewer.entities.getById(eid);
      if (ent) viewer.entities.remove(ent);
    }
    vectorEntities.current[layerId] = [];
  };

  const loadVector = async (layerId: string) => {
    if (!viewer) return;
    removeVector(layerId);
    const { data } = await offlineApi.layerGeojson(layerId);
    const features = data.features || [];
    const ids: string[] = [];
    for (let i = 0; i < features.length; i++) {
      const f = features[i];
      const geom = f.geometry;
      const props = f.properties || {};
      const eid = `${layerId}_${i}`;
      if (geom?.type === 'Point') {
        const [lon, lat] = geom.coordinates;
        viewer.entities.add({
          id: eid,
          name: props.name,
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: {
            pixelSize: props.type === 'city' ? 6 : 8,
            color:
              props.type === 'peak'
                ? Cesium.Color.fromCssColorString('#5eead4')
                : props.type === 'city'
                  ? Cesium.Color.fromCssColorString('#fbbf24')
                  : Cesium.Color.fromCssColorString('#7dd3fc'),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: props.name || '',
            font: '11px Space Grotesk, sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -10),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            show: layerId === 'landmarks',
          },
          properties: { [VECTOR_PROP]: layerId },
        });
        ids.push(eid);
      } else if (geom?.type === 'LineString') {
        const positions = geom.coordinates.flatMap(([lon, lat]: number[]) => [lon, lat]);
        viewer.entities.add({
          id: eid,
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(positions),
            width: 1.25,
            material: Cesium.Color.fromCssColorString('#94a3b8').withAlpha(0.7),
          },
          properties: { [VECTOR_PROP]: layerId },
        });
        ids.push(eid);
      } else if (geom?.type === 'Polygon') {
        const ring = geom.coordinates[0] as number[][];
        const hierarchy = ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
        viewer.entities.add({
          id: eid,
          polygon: {
            hierarchy,
            material: Cesium.Color.fromCssColorString('#2dd4bf').withAlpha(0.08),
            outline: true,
            outlineColor: Cesium.Color.fromCssColorString('#2dd4bf').withAlpha(0.5),
            height: 0,
          },
          properties: { [VECTOR_PROP]: layerId },
        });
        ids.push(eid);
      }
    }
    vectorEntities.current[layerId] = ids;
  };

  const ensureLayer = async (layerId: string, on: boolean) => {
    const layer = layers.find((l) => l.id === layerId);
    if (!layer || !viewer) return;

    if (layer.category === 'basemap' && layer.url_template) {
      if (on) {
        const style = layerId.includes('topo')
          ? 'topo'
          : layerId.includes('dark')
            ? 'dark'
            : 'satellite';
        switchBasemap(style);
      }
      return;
    }

    if (layer.type === 'geojson') {
      if (on) await loadVector(layerId);
      else removeVector(layerId);
      return;
    }

    if (layer.type === 'raster' && layer.path && on) {
      const url =
        `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(layer.path)}`;
      addAnalysisLayer(url);
      showNotification(`Showing ${layer.name}`, 'info');
    }
  };

  const toggleOfflineLayer = async (layerId: string) => {
    const next = !enabled[layerId];
    setEnabled((s) => ({ ...s, [layerId]: next }));
    try {
      await ensureLayer(layerId, next);
    } catch {
      showNotification('Could not toggle layer', 'error');
    }
  };

  const switchBasemap = (style: string) => {
    if (!viewer) return;
    setBasemapStyle(style);
    // Replace base imagery with offline tiles
    const layersCol = viewer.imageryLayers;
    while (layersCol.length > 0) {
      layersCol.remove(layersCol.get(0), true);
    }
    const provider = new Cesium.UrlTemplateImageryProvider({
      url: `/api/v1/offline/basemap/{z}/{x}/{y}.png?style=${encodeURIComponent(style)}`,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      maximumLevel: 10,
    });
    layersCol.addImageryProvider(provider);
    showNotification(`Basemap: ${style}`, 'info');
  };

  const coreLayers = [
    { id: 'terrain', name: 'Ellipsoid Terrain', description: 'Local offline terrain (no Ion)' },
    { id: 'aoi', name: 'Areas of Interest', description: 'User-defined AOIs' },
    { id: 'footprints', name: 'Scene Footprints', description: 'Uploaded scene boundaries' },
  ];

  const byCat = (cat: string) => layers.filter((l) => l.category === cat);

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-sateye-mist/80 uppercase tracking-wider flex items-center gap-2">
        <Layers className="w-4 h-4 text-sateye-teal" /> Layer Manager
      </h3>

      <div>
        <div className="text-[11px] uppercase tracking-[0.2em] text-sateye-mist/40 mb-1.5 flex items-center gap-1">
          <Map className="w-3 h-3" /> Offline basemap
        </div>
        <div className="grid grid-cols-3 gap-1">
          {['satellite', 'topo', 'dark'].map((style) => (
            <button
              key={style}
              onClick={() => switchBasemap(style)}
              className={`text-xs py-1.5 rounded capitalize ${
                basemapStyle === style
                  ? 'bg-sateye-teal text-sateye-ink'
                  : 'bg-sateye-panel text-sateye-mist/70 hover:bg-sateye-panel/80'
              }`}
            >
              {style}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1">
        {coreLayers.map((layer) => (
          <button
            key={layer.id}
            onClick={() => toggleLayer(layer.id)}
            className="w-full flex items-center gap-3 p-2 rounded hover:bg-sateye-panel transition-colors"
          >
            {layerVisibility[layer.id] !== false ? (
              <Eye className="w-4 h-4 text-sateye-teal" />
            ) : (
              <EyeOff className="w-4 h-4 text-sateye-mist/30" />
            )}
            <div className="text-left">
              <div className="text-sm">{layer.name}</div>
              <div className="text-xs text-sateye-mist/45">{layer.description}</div>
            </div>
          </button>
        ))}
      </div>

      {(['basemap', 'vector', 'elevation'] as const).map((cat) => {
        const list = byCat(cat);
        if (!list.length) return null;
        return (
          <div key={cat}>
            <div className="text-[11px] uppercase tracking-[0.2em] text-sateye-mist/40 mb-1.5 flex items-center gap-1">
              {cat === 'elevation' ? <Mountain className="w-3 h-3" /> : <Layers className="w-3 h-3" />}
              {cat === 'elevation' ? 'DEM / DTM / DSM' : cat}
            </div>
            <div className="space-y-1">
              {list.map((layer) => (
                <button
                  key={layer.id}
                  onClick={() => void toggleOfflineLayer(layer.id)}
                  className="w-full flex items-center gap-3 p-2 rounded hover:bg-sateye-panel transition-colors"
                >
                  {enabled[layer.id] ? (
                    <Eye className="w-4 h-4 text-sateye-teal" />
                  ) : (
                    <EyeOff className="w-4 h-4 text-sateye-mist/30" />
                  )}
                  <div className="text-left">
                    <div className="text-sm">
                      {layer.name}
                      {layer.subtype && (
                        <span className="ml-1 text-[10px] text-sateye-teal/80">{layer.subtype}</span>
                      )}
                    </div>
                    <div className="text-xs text-sateye-mist/45">{layer.description}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      <div className="space-y-2 pt-1">
        <label className="btn-secondary w-full flex items-center justify-center gap-2 text-xs cursor-pointer">
          <Upload className="w-3.5 h-3.5" /> Upload DEM / DTM / DSM
          <input
            ref={elevRef}
            type="file"
            accept=".tif,.tiff"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                const { data } = await offlineApi.uploadElevation(file, 'DEM');
                setLayers(data.layers || []);
                showNotification('Elevation model added', 'success');
              } catch {
                showNotification('Elevation upload failed', 'error');
              }
              e.target.value = '';
            }}
          />
        </label>
        <label className="btn-secondary w-full flex items-center justify-center gap-2 text-xs cursor-pointer">
          <Upload className="w-3.5 h-3.5" /> Upload Vector GeoJSON
          <input
            ref={vecRef}
            type="file"
            accept=".geojson,.json"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                const { data } = await offlineApi.uploadVector(file);
                setLayers(data.layers || []);
                showNotification('Vector layer added', 'success');
              } catch {
                showNotification('Vector upload failed', 'error');
              }
              e.target.value = '';
            }}
          />
        </label>
      </div>
    </div>
  );
}
