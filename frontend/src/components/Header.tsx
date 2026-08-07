import { Eye, WifiOff } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useMapStore } from '@/store/mapStore';

export default function Header() {
  const { user, offlineMode } = useAuthStore();
  const { mousePosition } = useMapStore();

  return (
    <header className="absolute top-0 left-0 right-0 z-30 flex items-center justify-between px-5 py-2.5 sateye-header">
      <div className="flex items-center gap-3">
        <div className="relative flex items-center justify-center w-9 h-9 rounded-md bg-sateye-teal/15 border border-sateye-teal/40">
          <Eye className="w-5 h-5 text-sateye-teal animate-pulse-soft" />
        </div>
        <div>
          <h1 className="brand-mark text-xl leading-none tracking-[0.18em]">SAT EYE</h1>
          <p className="text-[10px] uppercase tracking-[0.28em] text-sateye-mist/55 mt-0.5">
            Offline Earth Observation
          </p>
        </div>
      </div>

      <div className="hidden md:flex items-center gap-6 font-mono text-[11px] text-sateye-mist/70">
        <span>
          {mousePosition.latitude.toFixed(4)}°N&nbsp;&nbsp;{mousePosition.longitude.toFixed(4)}°E
        </span>
        <span className="text-sateye-mist/40">|</span>
        <span>148 GIS tools</span>
      </div>

      <div className="flex items-center gap-3">
        {offlineMode && (
          <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded border border-sateye-teal/30 bg-sateye-teal/10 text-sateye-teal">
            <WifiOff className="w-3.5 h-3.5" />
            Offline PC
          </span>
        )}
        <span className="text-xs text-sateye-mist/60">
          {user?.full_name || user?.username || 'Local Operator'}
        </span>
      </div>
    </header>
  );
}
