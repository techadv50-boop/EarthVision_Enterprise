import SearchPanel from '@/widgets/SearchPanel';
import LayerPanel from '@/widgets/LayerPanel';
import ImageryPanel from '@/widgets/ImageryPanel';
import AnalyticsPanel from '@/widgets/AnalyticsPanel';
import BookmarksPanel from '@/widgets/BookmarksPanel';
import AOIPanel from '@/widgets/AOIPanel';
import RasterPanel from '@/widgets/RasterPanel';
import ToolsPanel from '@/widgets/ToolsPanel';
import UploadPanel from '@/widgets/UploadPanel';
import { useUIStore } from '@/store/uiStore';
import { X } from 'lucide-react';

const PANELS = {
  search: { title: 'Search', component: SearchPanel },
  layers: { title: 'Layers', component: LayerPanel },
  imagery: { title: 'Time Stacks', component: ImageryPanel },
  upload: { title: 'Upload Imagery', component: UploadPanel },
  analytics: { title: 'Analytics', component: AnalyticsPanel },
  bookmarks: { title: 'Bookmarks', component: BookmarksPanel },
  aoi: { title: 'AOI', component: AOIPanel },
  raster: { title: 'Raster', component: RasterPanel },
  tools: { title: 'GIS Tools — 148', component: ToolsPanel },
} as const;

export default function SidePanel() {
  const { activePanel, setActivePanel } = useUIStore();

  if (!activePanel || !(activePanel in PANELS)) return null;

  const panel = PANELS[activePanel as keyof typeof PANELS];
  const Component = panel.component;

  return (
    <div className="absolute top-4 right-4 w-[20rem] max-h-[calc(100vh-6rem)] panel p-4 z-20 overflow-y-auto animate-slide-in">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold tracking-wide">{panel.title}</h2>
        <button onClick={() => setActivePanel(null)} className="p-1 hover:text-sateye-mist/60">
          <X className="w-5 h-5" />
        </button>
      </div>
      <Component />
    </div>
  );
}
