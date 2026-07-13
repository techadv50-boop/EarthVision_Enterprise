import { useCallback, useState } from 'react';
import { Globe, type GlobeController } from '../map/Globe';
import { TopBar } from '../widgets/TopBar';
import { StatusBar } from '../widgets/StatusBar';
import { SearchPanel } from '../widgets/SearchPanel';
import { LayerPanel } from '../widgets/LayerPanel';
import { AoiPanel } from '../widgets/AoiPanel';
import { CatalogPanel } from '../widgets/CatalogPanel';
import { AnalyticsPanel } from '../widgets/AnalyticsPanel';
import { MlPanel } from '../widgets/MlPanel';
import { BookmarksPanel } from '../widgets/BookmarksPanel';
import { ProjectsPanel } from '../widgets/ProjectsPanel';
import { AdminPanel } from '../widgets/AdminPanel';

export function WorkspacePage() {
  const [globe, setGlobe] = useState<GlobeController | null>(null);
  const onReady = useCallback((controller: GlobeController) => {
    setGlobe(controller);
  }, []);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <Globe onReady={onReady} />
      <TopBar />
      <SearchPanel globe={globe} />
      <LayerPanel globe={globe} />
      <AoiPanel globe={globe} />
      <CatalogPanel globe={globe} />
      <AnalyticsPanel />
      <MlPanel />
      <BookmarksPanel globe={globe} />
      <ProjectsPanel globe={globe} />
      <AdminPanel />
      <StatusBar />
    </div>
  );
}
