import SearchPanel from '@/widgets/SearchPanel';
import LayerPanel from '@/widgets/LayerPanel';
import ImageryPanel from '@/widgets/ImageryPanel';
import AnalyticsPanel from '@/widgets/AnalyticsPanel';
import BookmarksPanel from '@/widgets/BookmarksPanel';
import AdminPanel from '@/widgets/AdminPanel';
import AOIPanel from '@/widgets/AOIPanel';
import RasterPanel from '@/widgets/RasterPanel';
import { useUIStore } from '@/store/uiStore';
import { X } from 'lucide-react';

const PANELS = {
  search: { title: 'Search', component: SearchPanel },
  layers: { title: 'Layers', component: LayerPanel },
  imagery: { title: 'Imagery', component: ImageryPanel },
  analytics: { title: 'Analytics', component: AnalyticsPanel },
  bookmarks: { title: 'Bookmarks', component: BookmarksPanel },
  aoi: { title: 'AOI', component: AOIPanel },
  raster: { title: 'Raster', component: RasterPanel },
  admin: { title: 'Admin', component: AdminPanel },
} as const;

export default function SidePanel() {
  const { activePanel, setActivePanel } = useUIStore();

  if (!activePanel) return null;

  const panel = PANELS[activePanel];
  if (!panel) return null;
  const Component = panel.component;

  return (
    <div className="absolute top-4 right-4 w-80 max-h-[calc(100vh-2rem)] panel p-4 z-20 overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">{panel.title}</h2>
        <button onClick={() => setActivePanel(null)} className="p-1 hover:text-gray-400">
          <X className="w-5 h-5" />
        </button>
      </div>
      <Component />
    </div>
  );
}
