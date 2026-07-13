import { useEffect, useState } from 'react';
import { Bookmark, Plus, Trash2, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import { bookmarkService } from '../services/bookmarkService';
import { getErrorMessage } from '../services/api';
import type { GlobeController } from '../map/Globe';
import { Math as CesiumMath } from 'cesium';

interface Props {
  globe: GlobeController | null;
}

export function BookmarksPanel({ globe }: Props) {
  const { activePanel, setActivePanel, bookmarks, setBookmarks } = useMapStore();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activePanel !== 'bookmarks') return;
    bookmarkService.list().then(setBookmarks).catch(() => undefined);
  }, [activePanel, setBookmarks]);

  if (activePanel !== 'bookmarks') return null;

  const save = async () => {
    const viewer = globe?.getViewer();
    if (!viewer || !name.trim()) return;
    try {
      const carto = viewer.camera.positionCartographic;
      const bookmark = await bookmarkService.create({
        name: name.trim(),
        description: null,
        longitude: CesiumMath.toDegrees(carto.longitude),
        latitude: CesiumMath.toDegrees(carto.latitude),
        height: carto.height,
        heading: CesiumMath.toDegrees(viewer.camera.heading),
        pitch: CesiumMath.toDegrees(viewer.camera.pitch),
        roll: CesiumMath.toDegrees(viewer.camera.roll),
      });
      setBookmarks([bookmark, ...bookmarks]);
      setName('');
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const go = (b: (typeof bookmarks)[0]) => {
    globe?.flyTo(b.longitude, b.latitude, b.height);
  };

  const remove = async (id: string) => {
    await bookmarkService.remove(id);
    setBookmarks(bookmarks.filter((b) => b.id !== id));
  };

  return (
    <aside className="pointer-events-auto absolute left-3 top-20 z-20 w-[min(100%-1.5rem,20rem)] animate-fade-up md:left-4">
      <div className="ev-panel p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">Bookmarks</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mb-3 flex gap-2">
          <input
            className="ev-input"
            placeholder="Bookmark name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="button" className="ev-btn-primary px-3" onClick={save}>
            <Plus className="h-4 w-4" />
          </button>
        </div>
        {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
        <ul className="max-h-72 space-y-1 overflow-y-auto">
          {bookmarks.map((b) => (
            <li key={b.id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-earth-800/70">
              <button type="button" className="flex flex-1 items-center gap-2 text-left" onClick={() => go(b)}>
                <Bookmark className="h-3.5 w-3.5 text-soil-400" />
                <span className="text-xs">{b.name}</span>
              </button>
              <button type="button" className="ev-btn-ghost p-1" onClick={() => remove(b.id)}>
                <Trash2 className="h-3.5 w-3.5 text-red-400" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
