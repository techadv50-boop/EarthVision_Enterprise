import { useEffect } from 'react';
import GlobeViewer from '@/map/GlobeViewer';
import DrawingTools from '@/map/DrawingTools';
import MapControls from '@/map/MapControls';
import LeftSidebar from '@/components/LeftSidebar';
import DrawToolbar from '@/components/DrawToolbar';
import SidePanel from '@/components/SidePanel';
import Header from '@/components/Header';
import NotificationToast from '@/components/NotificationToast';
import DateSlider from '@/widgets/DateSlider';
import { useStackStore } from '@/store/stackStore';
import { offlineApi } from '@/services/api';

export default function DashboardPage() {
  const { loadStacks, ensureDemoStack } = useStackStore();

  useEffect(() => {
    void (async () => {
      try {
        await offlineApi.seed();
      } catch {
        /* seed best-effort */
      }
      await ensureDemoStack();
      await loadStacks();
    })();
  }, [loadStacks, ensureDemoStack]);

  return (
    <div className="relative w-screen h-screen overflow-hidden sateye-shell">
      <Header />
      <div className="absolute inset-0 pt-12">
        <GlobeViewer />
        <DrawingTools />
        <MapControls />
        <LeftSidebar />
        <DrawToolbar />
        <SidePanel />
        <DateSlider />
      </div>
      <NotificationToast />
    </div>
  );
}
