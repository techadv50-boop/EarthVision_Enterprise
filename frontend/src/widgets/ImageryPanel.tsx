import { useEffect } from 'react';
import { CalendarRange, Loader2, Layers } from 'lucide-react';
import { useStackStore } from '@/store/stackStore';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

export default function ImageryPanel() {
  const {
    stacks,
    activeStack,
    loading,
    loadStacks,
    setActiveStack,
    ensureDemoStack,
    sliderIndex,
  } = useStackStore();
  const { flyTo } = useMapStore();
  const { showNotification } = useUIStore();

  useEffect(() => {
    void loadStacks();
  }, [loadStacks]);

  return (
    <div className="space-y-4">
      <p className="text-xs text-sateye-mist/60">
        Place stacks group satellite images of the same location. When 2+ dates exist, the
        multi-date slider appears under the globe.
      </p>

      <button
        className="btn-secondary w-full text-sm"
        onClick={async () => {
          await ensureDemoStack();
          showNotification('Loaded 20-date demo stack', 'success');
        }}
      >
        Load 20-date demo stack
      </button>

      {loading ? (
        <div className="flex justify-center py-6">
          <Loader2 className="w-5 h-5 animate-spin text-sateye-mist/50" />
        </div>
      ) : (
        <div className="space-y-2">
          {stacks.length === 0 && (
            <div className="text-xs text-sateye-mist/45">
              No stacks yet. Upload imagery and assign a place name.
            </div>
          )}
          {stacks.map((stack) => (
            <button
              key={stack.id}
              onClick={() => {
                setActiveStack(stack);
                if (stack.longitude != null && stack.latitude != null) {
                  flyTo(stack.longitude, stack.latitude, 400000);
                }
              }}
              className={`w-full text-left p-3 rounded border transition-colors ${
                activeStack?.id === stack.id
                  ? 'border-sateye-teal/50 bg-sateye-teal/10'
                  : 'border-transparent bg-sateye-panel/60 hover:bg-sateye-panel'
              }`}
            >
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-sateye-teal shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium truncate">{stack.name}</div>
                  <div className="text-[11px] text-sateye-mist/45 flex items-center gap-1">
                    <CalendarRange className="w-3 h-3" />
                    {stack.image_count} dates
                    {stack.date_min && stack.date_max && (
                      <span>
                        · {stack.date_min} → {stack.date_max}
                      </span>
                    )}
                  </div>
                </div>
                {stack.has_slider && (
                  <span className="text-[10px] text-sateye-teal border border-sateye-teal/30 px-1.5 py-0.5 rounded">
                    Slider
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {activeStack && activeStack.images.length > 0 && (
        <div className="panel p-3 space-y-1 max-h-48 overflow-y-auto">
          <div className="text-[11px] uppercase tracking-wider text-sateye-mist/40 mb-1">
            Dates in stack
          </div>
          {activeStack.images.map((im, idx) => (
            <div
              key={im.id}
              className={`text-xs font-mono py-0.5 ${
                idx === sliderIndex ? 'text-sateye-teal' : 'text-sateye-mist/55'
              }`}
            >
              {im.acquisition_date} — {im.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
