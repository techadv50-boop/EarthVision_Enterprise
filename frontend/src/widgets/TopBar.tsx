import {
  Layers,
  Search,
  Satellite,
  ChartArea,
  Brain,
  Bookmark,
  FolderKanban,
  Settings,
  Pentagon,
  LogOut,
  Menu,
} from 'lucide-react';
import { useAuthStore } from '../store/authStore';
import { useMapStore, type ActivePanel } from '../store/mapStore';

const tools: Array<{ id: ActivePanel; icon: typeof Search; label: string }> = [
  { id: 'search', icon: Search, label: 'Search' },
  { id: 'layers', icon: Layers, label: 'Layers' },
  { id: 'aoi', icon: Pentagon, label: 'AOI' },
  { id: 'catalog', icon: Satellite, label: 'Catalog' },
  { id: 'analytics', icon: ChartArea, label: 'Analytics' },
  { id: 'ml', icon: Brain, label: 'AI / ML' },
  { id: 'bookmarks', icon: Bookmark, label: 'Bookmarks' },
  { id: 'projects', icon: FolderKanban, label: 'Projects' },
  { id: 'admin', icon: Settings, label: 'Admin' },
];

export function TopBar() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const { activePanel, setActivePanel } = useMapStore();

  return (
    <header className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-3 p-3 md:p-4">
      <div className="pointer-events-auto ev-panel flex items-center gap-3 px-3 py-2 animate-fade-up">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-orbit-500 to-earth-600 shadow-md animate-pulse-ring">
          <Satellite className="h-5 w-5 text-white" />
        </div>
        <div className="leading-tight">
          <div className="font-display text-sm font-semibold tracking-wide text-earth-50 md:text-base">
            EarthVision
          </div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-orbit-400">
            Enterprise
          </div>
        </div>
      </div>

      <nav className="pointer-events-auto ev-panel hidden items-center gap-1 p-1.5 md:flex animate-fade-up" style={{ animationDelay: '80ms' }}>
        {tools.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            type="button"
            title={label}
            onClick={() => setActivePanel(id)}
            className={`ev-btn-ghost rounded-lg px-2.5 py-2 ${
              activePanel === id
                ? 'bg-orbit-500/20 text-orbit-400'
                : 'text-earth-300'
            }`}
          >
            <Icon className="h-4 w-4" />
            <span className="hidden text-xs lg:inline">{label}</span>
          </button>
        ))}
      </nav>

      <div className="pointer-events-auto ev-panel flex items-center gap-2 px-3 py-2 animate-fade-up" style={{ animationDelay: '120ms' }}>
        <button
          type="button"
          className="ev-btn-ghost md:hidden"
          onClick={() => setActivePanel(activePanel === 'search' ? 'none' : 'search')}
        >
          <Menu className="h-4 w-4" />
        </button>
        <div className="hidden text-right sm:block">
          <div className="text-xs font-medium text-earth-100">{user?.full_name}</div>
          <div className="text-[10px] uppercase tracking-wider text-earth-400">
            {user?.role}
          </div>
        </div>
        <button type="button" className="ev-btn-ghost" onClick={logout} title="Sign out">
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
