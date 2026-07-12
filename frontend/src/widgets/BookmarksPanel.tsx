import { useEffect, useState } from 'react';
import * as Cesium from 'cesium';
import { Bookmark, Trash2, Plus } from 'lucide-react';
import { geoApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

export default function BookmarksPanel() {
  const { bookmarks, setBookmarks, flyTo, mousePosition, viewer } = useMapStore();
  const { showNotification } = useUIStore();
  const [name, setName] = useState('');

  useEffect(() => {
    loadBookmarks();
  }, []);

  const loadBookmarks = async () => {
    try {
      const { data } = await geoApi.bookmarks.list();
      setBookmarks(data);
    } catch {
      /* empty */
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    const camera = viewer?.camera;
    try {
      await geoApi.bookmarks.create({
        name,
        longitude: mousePosition.longitude,
        latitude: mousePosition.latitude,
        altitude: camera ? camera.positionCartographic.height : 10000,
        heading: camera ? Cesium.Math.toDegrees(camera.heading) : 0,
        pitch: camera ? Cesium.Math.toDegrees(camera.pitch) : -45,
      });
      setName('');
      await loadBookmarks();
      showNotification('Bookmark saved', 'success');
    } catch {
      showNotification('Failed to save bookmark', 'error');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await geoApi.bookmarks.delete(id);
      await loadBookmarks();
    } catch {
      showNotification('Failed to delete bookmark', 'error');
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Bookmarks</h3>
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Bookmark name..."
          className="input-field text-sm"
        />
        <button onClick={handleCreate} className="btn-primary px-3">
          <Plus className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-1 max-h-64 overflow-y-auto">
        {bookmarks.map((bm) => (
          <div key={bm.id} className="flex items-center gap-2 p-2 rounded hover:bg-gray-800 group">
            <button
              onClick={() =>
                flyTo(bm.longitude, bm.latitude, bm.altitude, {
                  heading: bm.heading,
                  pitch: bm.pitch,
                  roll: bm.roll,
                })
              }
              className="flex-1 text-left flex items-center gap-2"
            >
              <Bookmark className="w-4 h-4 text-yellow-400" />
              <div>
                <div className="text-sm">{bm.name}</div>
                <div className="text-xs text-gray-500">
                  {bm.latitude.toFixed(4)}°, {bm.longitude.toFixed(4)}°
                </div>
              </div>
            </button>
            <button
              onClick={() => handleDelete(bm.id)}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-opacity"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
        {bookmarks.length === 0 && (
          <p className="text-sm text-gray-500 text-center py-4">No bookmarks yet</p>
        )}
      </div>
    </div>
  );
}
