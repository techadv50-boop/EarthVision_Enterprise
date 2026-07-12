import GlobeViewer from '@/map/GlobeViewer';
import DrawingTools from '@/map/DrawingTools';
import MapControls from '@/map/MapControls';
import Toolbar from '@/components/Toolbar';
import SidePanel from '@/components/SidePanel';
import Header from '@/components/Header';
import NotificationToast from '@/components/NotificationToast';

export default function DashboardPage() {
  return (
    <div className="relative w-screen h-screen overflow-hidden">
      <Header />
      <div className="absolute inset-0 pt-12">
        <GlobeViewer />
        <DrawingTools />
        <MapControls />
        <Toolbar />
        <SidePanel />
      </div>
      <NotificationToast />
    </div>
  );
}
