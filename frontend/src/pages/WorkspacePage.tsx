import { useCallback, useMemo, useRef, useState } from 'react';
import { FlaskConical, LogOut, Mountain } from 'lucide-react';
import { LightMap } from '../map/LightMap';
import { MapToolbar } from '../components/map/MapToolbar';
import { MapLegend } from '../components/map/MapLegend';
import { PlaceStep } from '../components/workflow/PlaceStep';
import { ScenesStep } from '../components/workflow/ScenesStep';
import { AnalysisPanel } from '../components/workflow/AnalysisPanel';
import { TerrainPanel } from '../components/workflow/TerrainPanel';
import { BufferPanel } from '../components/workflow/BufferPanel';
import { useAuthStore } from '../store/authStore';
import {
  useWorkflowStore,
  type DrawnFeature,
  type PlaceSelection,
} from '../store/workflowStore';
import { catalogService, type SceneSummary } from '../services/catalogService';
import { analyticsService, type IndexName, type LegendInfo } from '../services/analyticsService';
import {
  terrainService,
  gisBufferService,
  type TerrainProduct,
  type TerrainResult,
} from '../services/terrainService';
import { gisService } from '../services/gisService';
import { getErrorMessage } from '../services/api';
import { footprintBbox } from '../utils/geoMath';
import { exportMapJpeg } from '../utils/exportMap';

function sceneBounds(
  scene: SceneSummary,
  place: PlaceSelection | null,
): [number, number, number, number] {
  return (
    footprintBbox(scene.footprint as GeoJSON.Geometry | null, place?.bbox) ??
    place?.bbox ?? [74.15, 31.35, 74.55, 31.7]
  );
}

function aoiBbox(
  aoi: GeoJSON.Feature | null,
  fallback: [number, number, number, number],
): [number, number, number, number] {
  if (aoi?.geometry.type === 'Polygon') {
    const ring = aoi.geometry.coordinates[0];
    const lons = ring.map((c) => c[0]);
    const lats = ring.map((c) => c[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  }
  return fallback;
}

export function WorkspacePage() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const mapHostRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [terrainLoading, setTerrainLoading] = useState(false);
  const [terrainResult, setTerrainResult] = useState<TerrainResult | null>(null);
  const [contourInterval, setContourInterval] = useState(25);
  const [observerHeight, setObserverHeight] = useState(1.7);
  const [bufferLoading, setBufferLoading] = useState(false);
  const [lastBufferDistance, setLastBufferDistance] = useState<number | null>(null);
  const [lastBufferArea, setLastBufferArea] = useState<number | null>(null);

  const {
    step,
    place,
    scenes,
    visibleSceneIds,
    focusSceneId,
    analysisOpen,
    terrainOpen,
    compareSceneId,
    indexResult,
    changeResult,
    selectedIndex,
    loadingScenes,
    loadingIndex,
    loadingOverlayIds,
    error,
    mapTool,
    aoiGeoJson,
    drawnFeature,
    measureLine,
    bufferGeoJson,
    measureLabel,
    overlays,
    layerOpacity,
    setPlace,
    setScenes,
    setFocusSceneId,
    setAnalysisOpen,
    setTerrainOpen,
    setCompareSceneId,
    setIndexResult,
    setChangeResult,
    setSelectedIndex,
    setLoadingScenes,
    setLoadingIndex,
    addLoadingOverlay,
    removeLoadingOverlay,
    setError,
    setStep,
    setMapTool,
    setAoiGeoJson,
    setDrawnFeature,
    setMeasureLine,
    setBufferGeoJson,
    setMeasureLabel,
    upsertOverlay,
    removeSceneOverlay,
    removeOverlaysByKind,
    setLayerOpacity,
    showScene,
    hideScene,
    clearAnalysis,
    clearDrawn,
    resetFromPlace,
    backToPlace,
  } = useWorkflowStore();

  const focusScene = useMemo(
    () => scenes.find((s) => s.id === focusSceneId) ?? null,
    [scenes, focusSceneId],
  );

  const hasVisibleScene = visibleSceneIds.length > 0;
  const rightPanel = analysisOpen ? 'indices' : terrainOpen ? 'terrain' : null;

  const analysisBbox = useMemo((): [number, number, number, number] => {
    const sceneOverlay = focusScene
      ? overlays.find((o) => o.kind === 'scene' && o.sceneId === focusScene.id)
      : null;
    if (sceneOverlay?.bounds) return sceneOverlay.bounds;
    if (place) return aoiBbox(aoiGeoJson, place.bbox);
    return [74.15, 31.35, 74.55, 31.7];
  }, [aoiGeoJson, focusScene, overlays, place]);

  const loadScenesForPlace = useCallback(
    async (selected: PlaceSelection) => {
      setPlace(selected);
      resetFromPlace();
      setLoadingScenes(true);
      setError(null);
      try {
        const bbox = aoiBbox(aoiGeoJson, selected.bbox);
        const result = await catalogService.search({
          collections: ['SENTINEL-1', 'SENTINEL-2', 'LANDSAT-8', 'LANDSAT-9', 'MODIS'],
          cloud_cover_max: 80,
          bbox: [...bbox],
          max_results: 20,
        });
        setScenes(result.items.slice(0, 20));
        setStep('browse');
      } catch (err) {
        setError(getErrorMessage(err));
        setStep('browse');
      } finally {
        setLoadingScenes(false);
      }
    },
    [aoiGeoJson, resetFromPlace, setError, setLoadingScenes, setPlace, setScenes, setStep],
  );

  const onPlaceClick = useCallback(
    async (lon: number, lat: number) => {
      if (step !== 'place') return;
      if (mapTool !== 'navigate') return;
      const pad = 0.18;
      try {
        const reverse = await gisService.reverseGeocode(lon, lat);
        await loadScenesForPlace({
          name: reverse.display_name || `Point ${lat.toFixed(3)}, ${lon.toFixed(3)}`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        });
      } catch {
        await loadScenesForPlace({
          name: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        });
      }
    },
    [loadScenesForPlace, mapTool, step],
  );

  const onDrawnFeature = useCallback(
    (feature: DrawnFeature) => {
      setDrawnFeature(feature);
      if (feature.type === 'LineString' && feature.geometry.type === 'LineString') {
        setMeasureLine(feature.geometry);
      }
      // Clear previous buffer when geometry changes
      setBufferGeoJson(null);
      removeOverlaysByKind('buffer');
      setLastBufferDistance(null);
      setLastBufferArea(null);
    },
    [removeOverlaysByKind, setBufferGeoJson, setDrawnFeature, setMeasureLine],
  );

  const loadSceneOverlay = useCallback(
    async (scene: SceneSummary) => {
      addLoadingOverlay(scene.id);
      setError(null);
      try {
        const bounds = sceneBounds(scene, place);
        const overlay = await analyticsService.sceneOverlay({
          scene_id: scene.id,
          collection: scene.collection,
          bbox: bounds,
          footprint: scene.footprint ?? null,
          sensing_time: scene.sensing_time ?? null,
          cloud_cover: scene.cloud_cover ?? null,
        });
        const tileUrl =
          overlay.tile_url || analyticsService.sceneTileUrl(scene.id);
        const label =
          overlay.label ||
          (scene.collection === 'SENTINEL-1'
            ? 'Sentinel-1 GRD (grayscale)'
            : scene.collection.startsWith('LANDSAT')
              ? `${scene.collection} true-color`
              : `${scene.collection} true-color (TCI)`);
        upsertOverlay({
          id: `scene-${scene.id}`,
          kind: 'scene',
          sceneId: scene.id,
          url: overlay.overlay_base64
            ? analyticsService.toDataUrl(overlay.overlay_base64)
            : '',
          tileUrl,
          bounds: overlay.bounds as [number, number, number, number],
          footprint: (overlay.footprint as GeoJSON.Polygon | null) ?? null,
          opacity: 1,
          label,
          renderMode: overlay.render_mode,
        });
      } catch (err) {
        setError(getErrorMessage(err));
        hideScene(scene.id);
      } finally {
        removeLoadingOverlay(scene.id);
      }
    },
    [
      addLoadingOverlay,
      hideScene,
      place,
      removeLoadingOverlay,
      setError,
      upsertOverlay,
    ],
  );

  const onToggleEye = async (scene: SceneSummary) => {
    if (visibleSceneIds.includes(scene.id)) {
      hideScene(scene.id);
      removeSceneOverlay(scene.id);
      if (visibleSceneIds.length <= 1) {
        removeOverlaysByKind('index');
        removeOverlaysByKind('change');
      }
      return;
    }
    showScene(scene.id);
    clearAnalysis();
    removeOverlaysByKind('index');
    removeOverlaysByKind('change');
    await loadSceneOverlay(scene);
  };

  const onFocus = (scene: SceneSummary) => {
    setFocusSceneId(scene.id);
  };

  const onPickIndex = async (index: IndexName) => {
    if (!focusScene) return;
    setSelectedIndex(index);
    setChangeResult(null);
    removeOverlaysByKind('change');
    setLoadingIndex(true);
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      const bounds =
        sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const result = await analyticsService.computeIndex(index, focusScene.id, bounds);
      setIndexResult(result);
      if (result.overlay_base64 && result.bounds) {
        upsertOverlay({
          id: `index-${focusScene.id}-${index}`,
          kind: 'index',
          sceneId: focusScene.id,
          url: analyticsService.toDataUrl(result.overlay_base64),
          bounds: result.bounds as [number, number, number, number],
          footprint: sceneOverlay?.footprint ?? null,
          opacity: layerOpacity,
          label: index,
        });
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingIndex(false);
    }
  };

  const onRunChange = async () => {
    if (!focusScene || !compareSceneId) return;
    setLoadingIndex(true);
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      const bounds =
        sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const result = await analyticsService.changeDetection({
        before_scene_id: compareSceneId,
        after_scene_id: focusScene.id,
        index: selectedIndex || 'NDVI',
        bbox: bounds,
        threshold: 0.12,
      });
      setChangeResult(result);
      upsertOverlay({
        id: `change-${compareSceneId}-${focusScene.id}`,
        kind: 'change',
        sceneId: focusScene.id,
        url: analyticsService.toDataUrl(result.overlay_base64),
        bounds: result.bounds as [number, number, number, number],
        footprint: sceneOverlay?.footprint ?? null,
        opacity: layerOpacity,
        label: `${result.index} change`,
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingIndex(false);
    }
  };

  const onRunTerrain = async (product: TerrainProduct) => {
    setTerrainLoading(true);
    setError(null);
    try {
      const line =
        measureLine ||
        (drawnFeature?.type === 'LineString' && drawnFeature.geometry.type === 'LineString'
          ? drawnFeature.geometry
          : null);

      let observer: [number, number] | undefined;
      let target: [number, number] | undefined;

      if (drawnFeature?.type === 'Point' && drawnFeature.geometry.type === 'Point') {
        observer = drawnFeature.geometry.coordinates as [number, number];
      } else if (place) {
        observer = [place.longitude, place.latitude];
      } else {
        const [w, s, e, n] = analysisBbox;
        observer = [(w + e) / 2, (s + n) / 2];
      }

      if (line && line.coordinates.length >= 2) {
        const first = line.coordinates[0];
        const last = line.coordinates[line.coordinates.length - 1];
        observer = [first[0], first[1]];
        target = [last[0], last[1]];
      }

      const result = await terrainService.compute({
        product,
        bbox: [...analysisBbox],
        aoi: aoiGeoJson?.geometry ?? null,
        size: 256,
        contour_interval: contourInterval,
        observer,
        target,
        observer_height_m: observerHeight,
        target_height_m: observerHeight,
        profile_line: line ?? undefined,
      });
      setTerrainResult(result);

      const bounds = result.bounds as [number, number, number, number];
      if (result.overlay_base64 || result.geojson) {
        upsertOverlay({
          id: `terrain-${product}`,
          kind: 'terrain',
          url: result.overlay_base64
            ? terrainService.toDataUrl(result.overlay_base64)
            : '',
          bounds,
          geojson: (result.geojson as GeoJSON.GeoJsonObject | null) ?? null,
          opacity: layerOpacity,
          label: product.replaceAll('_', ' '),
        });
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setTerrainLoading(false);
    }
  };

  const onApplyBuffer = async (distanceMeters: number) => {
    if (!drawnFeature) return;
    setBufferLoading(true);
    setError(null);
    try {
      const result = await gisBufferService.buffer(
        drawnFeature.geometry,
        distanceMeters,
      );
      setLastBufferDistance(result.distance_meters);
      setLastBufferArea(result.area_sq_meters ?? null);
      const bufferFeature: GeoJSON.Feature = {
        type: 'Feature',
        properties: { distance_meters: result.distance_meters },
        geometry: result.geometry as GeoJSON.Geometry,
      };
      upsertOverlay({
        id: 'buffer-layer',
        kind: 'buffer',
        url: '',
        bounds: result.bounds as [number, number, number, number],
        geojson: bufferFeature,
        opacity: layerOpacity,
        label: `Buffer ${distanceMeters} m`,
      });
      if (result.geometry.type === 'Polygon') {
        setBufferGeoJson(result.geometry as GeoJSON.Polygon);
      } else {
        setBufferGeoJson(null);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBufferLoading(false);
    }
  };

  const onClearBuffer = () => {
    setBufferGeoJson(null);
    removeOverlaysByKind('buffer');
    setLastBufferDistance(null);
    setLastBufferArea(null);
  };

  const onDownloadScene = () => {
    if (!focusScene) return;
    const bounds = sceneBounds(focusScene, place);
    const url = analyticsService.sceneDownloadUrl(focusScene.id, bounds);
    const token = localStorage.getItem('ev_access_token');
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        const href = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = href;
        a.download = `${focusScene.collection}_${focusScene.id}.png`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch(() => window.open(url, '_blank'));
  };

  const onExportJpeg = async () => {
    const host = mapHostRef.current;
    if (!host) return;
    const mapElement =
      (host.querySelector('.leaflet-container') as HTMLElement | null) || host;
    setExporting(true);
    try {
      const legend =
        terrainResult?.legend || changeResult?.legend || indexResult?.legend || null;
      await exportMapJpeg({
        mapElement,
        title: 'EarthVision Map Export',
        placeName: place?.name,
        legend,
        filename: `earthvision-${(place?.name || 'map').replace(/\W+/g, '_').slice(0, 40)}.jpg`,
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const legend: LegendInfo | null =
    (terrainResult?.legend as LegendInfo | null | undefined) ||
    changeResult?.legend ||
    indexResult?.legend ||
    null;

  const showRight =
    (rightPanel === 'indices' && hasVisibleScene && focusScene) ||
    rightPanel === 'terrain';

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--line)] bg-white px-3 py-2 sm:px-4">
        <div className="min-w-0">
          <div className="font-display text-sm font-semibold tracking-wide sm:text-base">
            EarthVision
          </div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">
            Light Explorer
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            className={`ev-btn inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ${
              terrainOpen
                ? 'bg-[var(--accent)] text-white'
                : 'border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent-soft)]'
            }`}
            onClick={() => {
              setTerrainOpen(!terrainOpen);
              if (!terrainOpen) setAnalysisOpen(false);
            }}
          >
            <Mountain className="h-4 w-4" />
            Terrain
          </button>
          {hasVisibleScene && (
            <button
              type="button"
              className={`ev-btn inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ${
                analysisOpen
                  ? 'bg-[var(--accent)] text-white'
                  : 'border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent-soft)]'
              }`}
              onClick={() => {
                setAnalysisOpen(!analysisOpen);
                if (!analysisOpen) setTerrainOpen(false);
              }}
            >
              <FlaskConical className="h-4 w-4" />
              Indices
            </button>
          )}
          <span className="hidden max-w-[10rem] truncate text-xs text-[var(--muted)] sm:inline">
            {user?.full_name}
          </span>
          <button type="button" className="ev-btn-ghost p-2" onClick={logout} title="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div
        className={`grid min-h-0 flex-1 ${
          showRight
            ? 'lg:grid-cols-[minmax(18rem,22rem)_1fr_minmax(18rem,22rem)]'
            : 'lg:grid-cols-[minmax(18rem,24rem)_1fr]'
        }`}
      >
        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto border-b border-[var(--line)] bg-white p-3 sm:p-4 lg:border-b-0 lg:border-r">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

          <BufferPanel
            hasGeometry={Boolean(drawnFeature)}
            geometryType={drawnFeature?.type ?? null}
            loading={bufferLoading}
            lastDistance={lastBufferDistance}
            lastArea={lastBufferArea}
            onApply={onApplyBuffer}
            onClear={onClearBuffer}
          />

          {step === 'place' && (
            <PlaceStep onSelect={loadScenesForPlace} busy={loadingScenes} />
          )}

          {step === 'browse' && place && (
            <ScenesStep
              placeName={place.name}
              scenes={scenes}
              visibleSceneIds={visibleSceneIds}
              focusSceneId={focusSceneId}
              loading={loadingScenes}
              loadingOverlayIds={loadingOverlayIds}
              onToggleEye={onToggleEye}
              onFocus={onFocus}
              onBack={backToPlace}
            />
          )}
        </aside>

        <section ref={mapHostRef} className="relative min-h-[40vh] lg:min-h-0" id="ev-map-host">
          <LightMap
            place={place}
            overlays={overlays}
            mapTool={mapTool}
            aoiGeoJson={aoiGeoJson}
            drawnFeature={drawnFeature}
            bufferGeoJson={bufferGeoJson}
            enablePlaceClick={step === 'place'}
            showGrid
            onPlaceClick={onPlaceClick}
            onAoiComplete={(feature) => {
              setAoiGeoJson(feature);
              if (feature.geometry.type === 'Polygon') {
                onDrawnFeature({
                  type: 'Polygon',
                  geometry: feature.geometry,
                  label: 'AOI',
                });
              }
              setMapTool('navigate');
            }}
            onDrawnFeature={onDrawnFeature}
            onMeasure={setMeasureLabel}
          />
          <MapToolbar
            tool={mapTool}
            measureLabel={measureLabel}
            layerOpacity={layerOpacity}
            onTool={(t) => {
              setMapTool(t);
              if (t === 'navigate') setMeasureLabel(null);
            }}
            onOpacity={setLayerOpacity}
            onClearAoi={() => {
              clearDrawn();
            }}
            onExportJpeg={onExportJpeg}
            hasAoi={Boolean(aoiGeoJson || drawnFeature || bufferGeoJson)}
            exporting={exporting}
          />
          <MapLegend legend={legend} />
          {step === 'place' && (
            <div className="pointer-events-none absolute bottom-14 left-1/2 z-[500] max-w-[90%] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1.5 text-center text-xs text-[var(--muted)] shadow">
              Search Lahore, click the map, or draw an AOI — then use eyes to show images
            </div>
          )}
        </section>

        {rightPanel === 'indices' && hasVisibleScene && focusScene && (
          <AnalysisPanel
            focusScene={focusScene}
            scenes={scenes}
            visibleSceneIds={visibleSceneIds}
            selectedIndex={selectedIndex}
            result={indexResult}
            changeResult={changeResult}
            compareSceneId={compareSceneId}
            loading={loadingIndex}
            onClose={() => setAnalysisOpen(false)}
            onPickIndex={onPickIndex}
            onCompareSceneId={setCompareSceneId}
            onRunChange={onRunChange}
            onDownloadScene={onDownloadScene}
          />
        )}

        {rightPanel === 'terrain' && (
          <aside className="flex min-h-0 flex-col border-t border-[var(--line)] bg-white lg:border-l lg:border-t-0">
            <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                Terrain tools
              </span>
              <button
                type="button"
                className="ev-btn-ghost text-xs"
                onClick={() => setTerrainOpen(false)}
              >
                Close
              </button>
            </div>
            <TerrainPanel
              loading={terrainLoading}
              result={terrainResult}
              contourInterval={contourInterval}
              observerHeight={observerHeight}
              onContourInterval={setContourInterval}
              onObserverHeight={setObserverHeight}
              onRun={onRunTerrain}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
