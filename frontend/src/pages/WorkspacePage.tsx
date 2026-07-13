import { useCallback, useMemo, useRef, useState } from 'react';
import { FlaskConical, LogOut } from 'lucide-react';
import { LightMap } from '../map/LightMap';
import { MapToolbar } from '../components/map/MapToolbar';
import { MapLegend } from '../components/map/MapLegend';
import { PlaceStep } from '../components/workflow/PlaceStep';
import { ScenesStep } from '../components/workflow/ScenesStep';
import { AnalysisPanel } from '../components/workflow/AnalysisPanel';
import { useAuthStore } from '../store/authStore';
import {
  useWorkflowStore,
  type PlaceSelection,
} from '../store/workflowStore';
import { catalogService, type SceneSummary } from '../services/catalogService';
import { analyticsService, type IndexName } from '../services/analyticsService';
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

  const {
    step,
    place,
    scenes,
    visibleSceneIds,
    focusSceneId,
    analysisOpen,
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
    measureLabel,
    overlays,
    layerOpacity,
    setPlace,
    setScenes,
    setFocusSceneId,
    setAnalysisOpen,
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
    setMeasureLabel,
    upsertOverlay,
    removeSceneOverlay,
    removeOverlaysByKind,
    setLayerOpacity,
    showScene,
    hideScene,
    clearAnalysis,
    resetFromPlace,
    backToPlace,
  } = useWorkflowStore();

  const focusScene = useMemo(
    () => scenes.find((s) => s.id === focusSceneId) ?? null,
    [scenes, focusSceneId],
  );

  const hasVisibleScene = visibleSceneIds.length > 0;

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
      // If no scenes left, analysis cleared by store
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
      // Prefer the on-map scene layer bounds so NDVI/etc. match the imagery extent
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
    // Capture the Leaflet map pane only (not the floating toolbar)
    const mapElement =
      (host.querySelector('.leaflet-container') as HTMLElement | null) || host;
    setExporting(true);
    try {
      const legend = changeResult?.legend || indexResult?.legend || null;
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

  const legend = changeResult?.legend || indexResult?.legend || null;

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
          {hasVisibleScene && (
            <button
              type="button"
              className={`ev-btn inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ${
                analysisOpen
                  ? 'bg-[var(--accent)] text-white'
                  : 'border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent-soft)]'
              }`}
              onClick={() => setAnalysisOpen(!analysisOpen)}
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
          analysisOpen && hasVisibleScene && focusScene
            ? 'lg:grid-cols-[minmax(18rem,22rem)_1fr_minmax(18rem,22rem)]'
            : 'lg:grid-cols-[minmax(18rem,24rem)_1fr]'
        }`}
      >
        <aside className="flex min-h-0 flex-col border-b border-[var(--line)] bg-white p-3 sm:p-4 lg:border-b-0 lg:border-r">
          {error && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

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
            enablePlaceClick={step === 'place'}
            showGrid
            onPlaceClick={onPlaceClick}
            onAoiComplete={(feature) => {
              setAoiGeoJson(feature);
              setMapTool('navigate');
            }}
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
              setAoiGeoJson(null);
              setMeasureLabel(null);
            }}
            onExportJpeg={onExportJpeg}
            hasAoi={Boolean(aoiGeoJson)}
            exporting={exporting}
          />
          <MapLegend legend={legend} />
          {step === 'place' && (
            <div className="pointer-events-none absolute bottom-14 left-1/2 z-[500] max-w-[90%] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1.5 text-center text-xs text-[var(--muted)] shadow">
              Search Lahore, click the map, or draw an AOI — then use eyes to show images
            </div>
          )}
        </section>

        {analysisOpen && hasVisibleScene && focusScene && (
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
      </div>
    </div>
  );
}
