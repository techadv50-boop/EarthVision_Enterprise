import { useCallback } from 'react';
import { LogOut } from 'lucide-react';
import { LightMap } from '../map/LightMap';
import { MapToolbar } from '../components/map/MapToolbar';
import { MapLegend } from '../components/map/MapLegend';
import { PlaceStep } from '../components/workflow/PlaceStep';
import { ScenesStep } from '../components/workflow/ScenesStep';
import { AnalyzeStep } from '../components/workflow/AnalyzeStep';
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

const STEP_LABELS = ['Place', 'Images', 'Analyze'] as const;

function sceneBounds(
  scene: SceneSummary,
  place: PlaceSelection | null,
): [number, number, number, number] {
  return (
    footprintBbox(scene.footprint as GeoJSON.Geometry | null, place?.bbox) ??
    place?.bbox ?? [74.15, 31.35, 74.55, 31.7]
  );
}

export function WorkspacePage() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const {
    step,
    place,
    scenes,
    selectedScene,
    compareScene,
    indexResult,
    changeResult,
    selectedIndex,
    loadingScenes,
    loadingIndex,
    loadingOverlay,
    error,
    mapTool,
    aoiGeoJson,
    measureLabel,
    overlays,
    layerOpacity,
    setPlace,
    setScenes,
    setSelectedScene,
    setCompareScene,
    setIndexResult,
    setChangeResult,
    setSelectedIndex,
    setLoadingScenes,
    setLoadingIndex,
    setLoadingOverlay,
    setError,
    setStep,
    setMapTool,
    setAoiGeoJson,
    setMeasureLabel,
    upsertOverlay,
    setLayerOpacity,
    resetFromPlace,
    backToScenes,
    backToPlace,
  } = useWorkflowStore();

  const loadScenesForPlace = useCallback(
    async (selected: PlaceSelection) => {
      setPlace(selected);
      resetFromPlace();
      setLoadingScenes(true);
      setError(null);
      try {
        const bbox = aoiGeoJson?.geometry.type === 'Polygon'
          ? (() => {
              const ring = aoiGeoJson.geometry.coordinates[0];
              const lons = ring.map((c) => c[0]);
              const lats = ring.map((c) => c[1]);
              return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)] as [
                number,
                number,
                number,
                number,
              ];
            })()
          : selected.bbox;

        const result = await catalogService.search({
          collections: ['SENTINEL-1', 'SENTINEL-2', 'LANDSAT-8', 'LANDSAT-9', 'MODIS'],
          cloud_cover_max: 80,
          bbox: [...bbox],
          max_results: 20,
        });
        setScenes(result.items.slice(0, 20));
        setStep('scenes');
      } catch (err) {
        setError(getErrorMessage(err));
        setStep('scenes');
      } finally {
        setLoadingScenes(false);
      }
    },
    [
      aoiGeoJson,
      resetFromPlace,
      setError,
      setLoadingScenes,
      setPlace,
      setScenes,
      setStep,
    ],
  );

  const onPlaceClick = useCallback(
    async (lon: number, lat: number) => {
      if (step !== 'place' && step !== 'scenes') return;
      if (mapTool !== 'navigate') return;
      setLoadingScenes(true);
      setError(null);
      try {
        const reverse = await gisService.reverseGeocode(lon, lat);
        const pad = 0.18;
        await loadScenesForPlace({
          name: reverse.display_name || `Point ${lat.toFixed(3)}, ${lon.toFixed(3)}`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        });
      } catch {
        const pad = 0.18;
        await loadScenesForPlace({
          name: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        });
      }
    },
    [loadScenesForPlace, mapTool, setError, setLoadingScenes, step],
  );

  const populateSceneOnMap = useCallback(
    async (scene: SceneSummary) => {
      setLoadingOverlay(true);
      setError(null);
      try {
        const bounds = sceneBounds(scene, place);
        const overlay = await analyticsService.sceneOverlay({
          scene_id: scene.id,
          collection: scene.collection,
          bbox: bounds,
          footprint: scene.footprint ?? null,
        });
        upsertOverlay({
          id: `scene-${scene.id}`,
          kind: 'scene',
          url: analyticsService.toDataUrl(overlay.overlay_base64),
          bounds: overlay.bounds as [number, number, number, number],
          opacity: layerOpacity,
          label: scene.name,
        });
      } catch (err) {
        setError(getErrorMessage(err));
      } finally {
        setLoadingOverlay(false);
      }
    },
    [layerOpacity, place, setError, setLoadingOverlay, upsertOverlay],
  );

  const onSelectScene = async (scene: SceneSummary) => {
    setSelectedScene(scene);
    setCompareScene(null);
    setIndexResult(null);
    setChangeResult(null);
    setSelectedIndex(null);
    setStep('analyze');
    await populateSceneOnMap(scene);
  };

  const onPickIndex = async (index: IndexName) => {
    if (!selectedScene) return;
    setSelectedIndex(index);
    setChangeResult(null);
    setLoadingIndex(true);
    setError(null);
    try {
      const bounds = sceneBounds(selectedScene, place);
      const result = await analyticsService.computeIndex(index, selectedScene.id, bounds);
      setIndexResult(result);
      if (result.overlay_base64 && result.bounds) {
        upsertOverlay({
          id: `index-${selectedScene.id}-${index}`,
          kind: 'index',
          url: analyticsService.toDataUrl(result.overlay_base64),
          bounds: result.bounds as [number, number, number, number],
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
    if (!selectedScene || !compareScene) return;
    setLoadingIndex(true);
    setError(null);
    try {
      const bounds = sceneBounds(selectedScene, place);
      const result = await analyticsService.changeDetection({
        before_scene_id: compareScene.id,
        after_scene_id: selectedScene.id,
        index: selectedIndex || 'NDVI',
        bbox: bounds,
        threshold: 0.12,
      });
      setChangeResult(result);
      upsertOverlay({
        id: `change-${compareScene.id}-${selectedScene.id}`,
        kind: 'change',
        url: analyticsService.toDataUrl(result.overlay_base64),
        bounds: result.bounds as [number, number, number, number],
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
    if (!selectedScene) return;
    const bounds = sceneBounds(selectedScene, place);
    const url = analyticsService.sceneDownloadUrl(selectedScene.id, bounds);
    const token = localStorage.getItem('ev_access_token');
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        const href = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = href;
        a.download = `${selectedScene.collection}_${selectedScene.id}.png`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch(() => window.open(url, '_blank'));
  };

  const stepIndex = step === 'place' ? 0 : step === 'scenes' ? 1 : 2;
  const legend =
    changeResult?.legend ||
    indexResult?.legend ||
    null;

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

        <nav className="flex items-center gap-1 sm:gap-2" aria-label="Workflow steps">
          {STEP_LABELS.map((label, i) => (
            <div key={label} className="flex items-center gap-1 sm:gap-2">
              <div
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                  i <= stepIndex
                    ? 'bg-[var(--accent)] text-white'
                    : 'bg-[var(--line)] text-[var(--muted)]'
                }`}
              >
                {i + 1}
              </div>
              <span
                className={`hidden text-xs sm:inline ${
                  i === stepIndex ? 'font-semibold text-[var(--ink)]' : 'text-[var(--muted)]'
                }`}
              >
                {label}
              </span>
              {i < STEP_LABELS.length - 1 && (
                <span className="mx-0.5 hidden h-px w-4 bg-[var(--line)] sm:block" />
              )}
            </div>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <span className="hidden max-w-[10rem] truncate text-xs text-[var(--muted)] sm:inline">
            {user?.full_name}
          </span>
          <button type="button" className="ev-btn-ghost p-2" onClick={logout} title="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(20rem,26rem)_1fr]">
        <aside className="flex min-h-0 flex-col border-b border-[var(--line)] bg-white p-3 sm:p-4 lg:border-b-0 lg:border-r">
          {(error || loadingOverlay) && (
            <div
              className={`mb-3 rounded-lg px-3 py-2 text-xs ${
                error
                  ? 'border border-red-200 bg-red-50 text-red-700'
                  : 'border border-[var(--line)] bg-[var(--accent-soft)] text-[var(--accent)]'
              }`}
            >
              {error || 'Loading imagery on map…'}
            </div>
          )}

          {step === 'place' && (
            <PlaceStep onSelect={loadScenesForPlace} busy={loadingScenes} />
          )}

          {step === 'scenes' && place && (
            <ScenesStep
              placeName={place.name}
              scenes={scenes}
              loading={loadingScenes}
              onSelect={onSelectScene}
              onBack={backToPlace}
            />
          )}

          {step === 'analyze' && selectedScene && (
            <AnalyzeStep
              scene={selectedScene}
              scenes={scenes}
              selectedIndex={selectedIndex}
              result={indexResult}
              changeResult={changeResult}
              compareScene={compareScene}
              loading={loadingIndex}
              onPickIndex={onPickIndex}
              onCompareScene={setCompareScene}
              onRunChange={onRunChange}
              onBack={backToScenes}
              onDownloadScene={onDownloadScene}
            />
          )}
        </aside>

        <section className="relative min-h-[40vh] lg:min-h-0">
          <LightMap
            place={place}
            scenes={scenes}
            selectedScene={selectedScene}
            overlays={overlays}
            mapTool={mapTool}
            aoiGeoJson={aoiGeoJson}
            enablePlaceClick={step === 'place' || step === 'scenes'}
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
            onTool={setMapTool}
            onOpacity={setLayerOpacity}
            onClearAoi={() => {
              setAoiGeoJson(null);
              setMeasureLabel(null);
            }}
            hasAoi={Boolean(aoiGeoJson)}
          />
          <MapLegend legend={legend} />
          {step === 'place' && mapTool === 'navigate' && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 z-[500] max-w-[90%] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1.5 text-center text-xs text-[var(--muted)] shadow">
              Search Lahore, click the map, or use AOI / measure tools above
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
