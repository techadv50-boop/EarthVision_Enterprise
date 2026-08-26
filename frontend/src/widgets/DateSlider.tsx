import { useEffect, useMemo } from 'react';
import { Calendar, ChevronLeft, ChevronRight, Play } from 'lucide-react';
import { useStackStore } from '@/store/stackStore';
import { useMapStore } from '@/store/mapStore';

/**
 * Multi-date imagery slider.
 * Range is strictly 0 … image_count-1 (maximum = number of uploaded dated images).
 */
export default function DateSlider() {
  const { activeStack, sliderIndex, setSliderIndex, selectByDateIndex } = useStackStore();
  const { flyTo, viewer } = useMapStore();

  const images = activeStack?.images ?? [];
  const imageCount = images.length;
  const maxIndex = Math.max(0, imageCount - 1);
  const show = Boolean(activeStack && imageCount >= 2);
  const safeIndex = Math.min(Math.max(0, sliderIndex), maxIndex);

  const current = images[safeIndex];
  const dateLabel = useMemo(() => {
    if (!current?.acquisition_date) return '—';
    const t = current.acquisition_time || current.metadata?.acquisition_time;
    return t ? `${current.acquisition_date} ${String(t)}` : current.acquisition_date;
  }, [current]);

  useEffect(() => {
    if (!activeStack) return;
    if (sliderIndex > maxIndex) setSliderIndex(maxIndex);
  }, [activeStack, maxIndex, setSliderIndex, sliderIndex]);

  useEffect(() => {
    if (!show || !current) return;
    const isDemo = current.is_demo || current.file_path?.startsWith('demo://');
    const path = current.working_path || current.file_path;
    if (!isDemo && path) {
      const url =
        `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(path)}`;
      useMapStore.getState().addAnalysisLayer(url);
    }
  }, [show, current, safeIndex]);

  useEffect(() => {
    if (!activeStack?.longitude || !activeStack?.latitude || !viewer) return;
  }, [activeStack?.id, activeStack?.latitude, activeStack?.longitude, viewer]);

  if (!show) return null;

  const pct = maxIndex <= 0 ? 0 : (safeIndex / maxIndex) * 100;

  return (
    <div className="absolute bottom-8 left-[22rem] right-4 md:left-1/2 md:-translate-x-1/2 md:right-auto z-30 w-[min(720px,calc(100vw-24rem))] animate-fade-in">
      <div className="panel px-5 py-4 border-sateye-teal/25 shadow-glow">
        <div className="flex items-center justify-between mb-3 gap-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.25em] text-sateye-teal/80">
              Multi-date slider
            </div>
            <div className="font-semibold truncate">{activeStack?.name}</div>
            <div className="text-xs text-sateye-mist/55">
              {imageCount} images · slider max {imageCount} · same place · different dates
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Calendar className="w-4 h-4 text-sateye-teal" />
            <span className="font-mono text-sm text-sateye-teal">{dateLabel}</span>
            <span className="text-xs text-sateye-mist/45">
              {safeIndex + 1}/{imageCount}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            className="p-1.5 rounded hover:bg-sateye-panel text-sateye-mist/70 disabled:opacity-30"
            onClick={() => setSliderIndex(safeIndex - 1)}
            disabled={safeIndex <= 0}
            title="Previous image"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>

          <div className="flex-1 relative pt-1">
            <input
              type="range"
              min={0}
              max={maxIndex}
              step={1}
              value={safeIndex}
              onChange={(e) => {
                const idx = Number(e.target.value);
                // Hard clamp to available images only
                selectByDateIndex(Math.max(0, Math.min(idx, maxIndex)));
              }}
              className="date-slider w-full"
              style={{ '--pct': `${pct}%` } as React.CSSProperties}
              aria-valuemin={0}
              aria-valuemax={maxIndex}
              aria-valuenow={safeIndex}
              aria-label={`Image ${safeIndex + 1} of ${imageCount}`}
            />
            <div className="flex justify-between mt-1 text-[10px] font-mono text-sateye-mist/40">
              <span>{images[0]?.acquisition_date}</span>
              <span>
                max {imageCount}
              </span>
              <span>{images[maxIndex]?.acquisition_date}</span>
            </div>
          </div>

          <button
            className="p-1.5 rounded hover:bg-sateye-panel text-sateye-mist/70 disabled:opacity-30"
            onClick={() => setSliderIndex(safeIndex + 1)}
            disabled={safeIndex >= maxIndex}
            title="Next image"
          >
            <ChevronRight className="w-5 h-5" />
          </button>

          <button
            className="p-1.5 rounded bg-sateye-teal/20 text-sateye-teal hover:bg-sateye-teal/30"
            title="Fly to place"
            onClick={() => {
              if (activeStack?.longitude != null && activeStack?.latitude != null) {
                flyTo(activeStack.longitude, activeStack.latitude, 400000);
              }
            }}
          >
            <Play className="w-4 h-4" />
          </button>
        </div>

        {current?.label && (
          <div className="mt-2 text-xs text-sateye-mist/50 truncate">
            {current.label}
            {current.original_format && ` · ${current.original_format}`}
            {current.cloud_cover != null && ` · cloud ${current.cloud_cover}%`}
          </div>
        )}
      </div>
    </div>
  );
}
