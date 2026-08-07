import {
  Search, Layers, Satellite, BarChart3, Bookmark, Wrench,
  Pentagon, Square, Circle, MapPin, Ruler, Navigation, Trash2, Images, Upload,
} from 'lucide-react';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

const TOOLS = [
  { id: 'navigate' as const, icon: Navigation, label: 'Navigate' },
  { id: 'polygon' as const, icon: Pentagon, label: 'Polygon' },
  { id: 'rectangle' as const, icon: Square, label: 'Rectangle' },
  { id: 'circle' as const, icon: Circle, label: 'Circle' },
  { id: 'marker' as const, icon: MapPin, label: 'Marker' },
  { id: 'measure' as const, icon: Ruler, label: 'Measure' },
];

const PANELS = [
  { id: 'upload' as const, icon: Upload, label: 'Upload Imagery' },
  { id: 'layers' as const, icon: Layers, label: 'Layers' },
  { id: 'tools' as const, icon: Wrench, label: 'GIS Tools (148)' },
  { id: 'imagery' as const, icon: Satellite, label: 'Time Stacks' },
  { id: 'analytics' as const, icon: BarChart3, label: 'Analytics' },
  { id: 'raster' as const, icon: Images, label: 'Raster' },
  { id: 'aoi' as const, icon: Pentagon, label: 'AOI' },
  { id: 'search' as const, icon: Search, label: 'Search' },
  { id: 'bookmarks' as const, icon: Bookmark, label: 'Bookmarks' },
];

export default function Toolbar() {
  const { activeTool, setActiveTool, clearGeometries } = useMapStore();
  const { activePanel, setActivePanel } = useUIStore();

  return (
    <div className="absolute top-4 left-4 z-20 flex flex-col gap-2 animate-slide-in">
      <div className="panel p-1 flex flex-col gap-0.5">
        {TOOLS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => setActiveTool(id)}
            title={label}
            className={`p-2 rounded transition-colors ${
              activeTool === id ? 'bg-sateye-teal text-sateye-ink' : 'hover:bg-sateye-panel text-sateye-mist/70'
            }`}
          >
            <Icon className="w-5 h-5" />
          </button>
        ))}
        <button
          onClick={clearGeometries}
          title="Clear drawings"
          className="p-2 rounded hover:bg-sateye-panel text-sateye-mist/70"
        >
          <Trash2 className="w-5 h-5" />
        </button>
      </div>

      <div className="panel p-1 flex flex-col gap-0.5">
        {PANELS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => setActivePanel(id)}
            title={label}
            className={`p-2 rounded transition-colors ${
              activePanel === id ? 'bg-sateye-teal text-sateye-ink' : 'hover:bg-sateye-panel text-sateye-mist/70'
            }`}
          >
            <Icon className="w-5 h-5" />
          </button>
        ))}
      </div>
    </div>
  );
}
