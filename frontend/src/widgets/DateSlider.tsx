import { useEffect, useMemo } from 'react';
import { Calendar, ChevronLeft, ChevronRight, Play } from 'lucide-react';
import { useStackStore } from '@/store/stackStore';
import { useMapStore } from '@/store/mapStore';

/**
 * Multi-date imagery slider. Visible when the active place stack has 2+ images
 * (designed for stacks of ~20 dates of the same place).
 */
export default function DateSlider() {
  const { activeStack, sliderIndex, setSliderIndex, selectByDateIndex } = useStackStore();
  const { flyTo, viewer } = useMapStore();

  const images = activeStack?.images ?? [];
  const show = Boolean(activeStack && images.length >= 2);

  const current = images[sliderIndex];
  const dateLabel = useMemo(() => {
    if (!current?.acquisition_date) return '—';
    return current.acquisition_date;
  }, [current]);

  useEffect(() => {
    if (!show || !current) return;
    // Demo images have virtual paths — show footprint / fly only
    const isDemo = current.is_demo || current.file_path?.startsWith('demo://');
    if (!isDemo && current.file_path) {
      // Use analysis layer path via raster tiles when real file exists
      const url =
        `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(current.file_path)}`;
      useMapStore.getState().addAnalysisLayer(url);
    }
  }, [show, current, sliderIndex]);

  useEffect(() => {
    if (!activeStack?.longitude || !activeStack?.latitude || !viewer) return;
    // Soft fly when stack first selected
  }, [activeStack?.id, viewer]);

  if (!show) return null;

  const pct = images.length <= 1 ? 0 : (sliderIndex / (images.length - 1)) * 100;

  return (
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-30 w-[min(720px,92vw)] animate-fade-in">
      <div className="panel px-5 py-4 border-sateye-teal/25 shadow-glow">
        <div className="flex items-center justify-between mb-3 gap-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.25em] text-sateye-teal/80">
              Multi-date slider
            </div>
            <div className="font-semibold truncate">{activeStack?.name}</div>
            <div className="text-xs text-sateye-mist/55">
              {images.length} images · same place · different dates
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Calendar className="w-4 h-4 text-sateye-teal" />
            <span className="font-mono text-sm text-sateye-teal">{dateLabel}</span>
            <span className="text-xs text-sateye-mist/45">
              {sliderIndex + 1}/{images.length}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            className="p-1.5 rounded hover:bg-sateye-panel text-sateye-mist/70"
            onClick={() => setSliderIndex(sliderIndex - 1)}
            disabled={sliderIndex <= 0}
            title="Previous date"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>

          <div className="flex-1 relative pt-1">
            <input
              type="range"
              min={0}
              max={images.length - 1}
              value={sliderIndex}
              onChange={(e) => {
                const idx = Number(e.target.value);
                selectByDateIndex(idx);
              }}
              className="date-slider w-full"
              style={{ '--pct': `${pct}%` } as React.CSSProperties}
            />
            <div className="flex justify-between mt-1 text-[10px] font-mono text-sateye-mist/40">
              <span>{images[0]?.acquisition_date}</span>
              <span>{images[images.length - 1]?.acquisition_date}</span>
            </div>
          </div>

          <button
            className="p-1.5 rounded hover:bg-sateye-panel text-sateye-mist/70"
            onClick={() => setSliderIndex(sliderIndex + 1)}
            disabled={sliderIndex >= images.length - 1}
            title="Next date"
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
            {current.cloud_cover != null && ` · cloud ${current.cloud_cover}%`}
          </div>
        )}
      </div>
    </div>
  );
}
