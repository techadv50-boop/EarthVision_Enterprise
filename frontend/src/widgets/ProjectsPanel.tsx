import { useEffect, useState } from 'react';
import { FolderKanban, Plus, Trash2, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import { projectService, type Project } from '../services/projectService';
import { getErrorMessage } from '../services/api';
import type { GlobeController } from '../map/Globe';

interface Props {
  globe: GlobeController | null;
}

export function ProjectsPanel({ globe }: Props) {
  const { activePanel, setActivePanel, aoiGeoJson } = useMapStore();
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    projectService
      .list()
      .then((data) => setProjects(data.items))
      .catch((err) => setError(getErrorMessage(err)));
  };

  useEffect(() => {
    if (activePanel === 'projects') load();
  }, [activePanel]);

  if (activePanel !== 'projects') return null;

  const create = async () => {
    if (!name.trim()) return;
    try {
      const viewer = globe?.getViewer();
      let center_lon: number | undefined;
      let center_lat: number | undefined;
      if (viewer) {
        const c = viewer.camera.positionCartographic;
        center_lon = (c.longitude * 180) / Math.PI;
        center_lat = (c.latitude * 180) / Math.PI;
      }
      await projectService.create({
        name: name.trim(),
        aoi_geojson: aoiGeoJson?.geometry ?? null,
        center_lon,
        center_lat,
      });
      setName('');
      load();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const remove = async (id: string) => {
    await projectService.remove(id);
    load();
  };

  const open = (p: Project) => {
    if (p.center_lon != null && p.center_lat != null) {
      globe?.flyTo(p.center_lon, p.center_lat, 300_000);
    }
  };

  return (
    <aside className="pointer-events-auto absolute left-3 top-20 z-20 w-[min(100%-1.5rem,22rem)] animate-fade-up md:left-4">
      <div className="ev-panel p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">Projects</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mb-3 flex gap-2">
          <input
            className="ev-input"
            placeholder="New project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="button" className="ev-btn-primary px-3" onClick={create}>
            <Plus className="h-4 w-4" />
          </button>
        </div>
        {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
        <ul className="max-h-80 space-y-1 overflow-y-auto">
          {projects.map((p) => (
            <li key={p.id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-earth-800/70">
              <button type="button" className="flex flex-1 items-center gap-2 text-left" onClick={() => open(p)}>
                <FolderKanban className="h-3.5 w-3.5 text-orbit-400" />
                <div>
                  <div className="text-xs font-medium">{p.name}</div>
                  <div className="text-[10px] text-earth-500">{p.status}</div>
                </div>
              </button>
              <button type="button" className="ev-btn-ghost p-1" onClick={() => remove(p.id)}>
                <Trash2 className="h-3.5 w-3.5 text-red-400" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
