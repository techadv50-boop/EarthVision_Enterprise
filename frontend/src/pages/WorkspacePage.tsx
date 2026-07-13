import { useCallback } from 'react';
import { LogOut } from 'lucide-react';
import { LightMap } from '../map/LightMap';
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

const STEP_LABELS = ['Place', 'Images', 'Analyze'] as const;

export function WorkspacePage() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const {
    step,
    place,
    scenes,
    selectedScene,
    indexResult,
    selectedIndex,
    loadingScenes,
    loadingIndex,
    error,
    setPlace,
    setScenes,
    setSelectedScene,
    setIndexResult,
    setSelectedIndex,
    setLoadingScenes,
    setLoadingIndex,
    setError,
    setStep,
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
        const result = await catalogService.search({
          collections: ['SENTINEL-1', 'SENTINEL-2', 'LANDSAT-8', 'LANDSAT-9', 'MODIS'],
          cloud_cover_max: 80,
          bbox: [...selected.bbox],
          max_results: 20,
        });
        // Prefer newest first (API already orders; keep top 20)
        const items = result.items.slice(0, 20);
        setScenes(items);
        setStep('scenes');
      } catch (err) {
        setError(getErrorMessage(err));
        setStep('scenes');
      } finally {
        setLoadingScenes(false);
      }
    },
    [
      resetFromPlace,
      setError,
      setLoadingScenes,
      setPlace,
      setScenes,
      setStep,
    ],
  );

  const onMapClick = useCallback(
    async (lon: number, lat: number) => {
      if (step !== 'place' && step !== 'scenes') return;
      setLoadingScenes(true);
      setError(null);
      try {
        const reverse = await gisService.reverseGeocode(lon, lat);
        const pad = 0.18;
        const selected: PlaceSelection = {
          name: reverse.display_name || `Point ${lat.toFixed(3)}, ${lon.toFixed(3)}`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        };
        await loadScenesForPlace(selected);
      } catch (err) {
        const pad = 0.18;
        await loadScenesForPlace({
          name: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`,
          longitude: lon,
          latitude: lat,
          bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
        });
        if (err) setError(getErrorMessage(err));
      }
    },
    [loadScenesForPlace, setError, setLoadingScenes, step],
  );

  const onSelectScene = (scene: SceneSummary) => {
    setSelectedScene(scene);
    setIndexResult(null);
    setSelectedIndex(null);
    setStep('analyze');
  };

  const onPickIndex = async (index: IndexName) => {
    if (!selectedScene) return;
    setSelectedIndex(index);
    setLoadingIndex(true);
    setError(null);
    try {
      const result = await analyticsService.computeIndex(index, selectedScene.id);
      setIndexResult(result);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingIndex(false);
    }
  };

  const stepIndex = step === 'place' ? 0 : step === 'scenes' ? 1 : 2;

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
          {error && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
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
              selectedIndex={selectedIndex}
              result={indexResult}
              loading={loadingIndex}
              onPickIndex={onPickIndex}
              onBack={backToScenes}
            />
          )}
        </aside>

        <section className="relative min-h-[40vh] lg:min-h-0">
          <LightMap
            place={place}
            scenes={scenes}
            selectedScene={selectedScene}
            onMapClick={onMapClick}
          />
          {step === 'place' && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 z-[500] max-w-[90%] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1.5 text-center text-xs text-[var(--muted)] shadow">
              Click the map to pick an area — or search Lahore on the left
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
