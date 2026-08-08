import {
  Circle, MapPin, Navigation, Pentagon, Ruler, Square, Trash2,
} from 'lucide-react';
import { useMapStore } from '@/store/mapStore';

const TOOLS = [
  { id: 'navigate' as const, icon: Navigation, label: 'Navigate' },
  { id: 'polygon' as const, icon: Pentagon, label: 'Draw polygon' },
  { id: 'rectangle' as const, icon: Square, label: 'Draw rectangle' },
  { id: 'circle' as const, icon: Circle, label: 'Draw circle' },
  { id: 'marker' as const, icon: MapPin, label: 'Point marker' },
  { id: 'measure' as const, icon: Ruler, label: 'Measure' },
];

/** Compact floating draw tools (right of left data sidebar). */
export default function DrawToolbar() {
  const { activeTool, setActiveTool, clearGeometries } = useMapStore();

  return (
    <div className="absolute top-4 left-[21.25rem] z-20 panel p-1 flex flex-col gap-0.5 animate-slide-in">
      {TOOLS.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          type="button"
          onClick={() => setActiveTool(id)}
          title={label}
          className={`p-2 rounded transition-colors ${
            activeTool === id ? 'bg-sateye-teal text-sateye-ink' : 'hover:bg-sateye-panel text-sateye-mist/70'
          }`}
        >
          <Icon className="w-4 h-4" />
        </button>
      ))}
      <button
        type="button"
        onClick={clearGeometries}
        title="Clear drawings"
        className="p-2 rounded hover:bg-sateye-panel text-sateye-mist/70"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}
