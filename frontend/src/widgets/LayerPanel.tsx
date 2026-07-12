import { Layers, Eye, EyeOff } from 'lucide-react';
import { useMapStore } from '@/store/mapStore';

const LAYERS = [
  { id: 'terrain', name: 'Terrain', description: 'Cesium World Terrain' },
  { id: 'imagery', name: 'Satellite Imagery', description: 'Bing Maps Aerial' },
  { id: 'footprints', name: 'Scene Footprints', description: 'Cached scene boundaries' },
  { id: 'aoi', name: 'Areas of Interest', description: 'User-defined AOIs' },
];

export default function LayerPanel() {
  const { layerVisibility, toggleLayer } = useMapStore();

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <Layers className="w-4 h-4" /> Layer Manager
      </h3>
      <div className="space-y-1">
        {LAYERS.map((layer) => (
          <button
            key={layer.id}
            onClick={() => toggleLayer(layer.id)}
            className="w-full flex items-center gap-3 p-2 rounded hover:bg-gray-800 transition-colors"
          >
            {layerVisibility[layer.id] ? (
              <Eye className="w-4 h-4 text-earth-400" />
            ) : (
              <EyeOff className="w-4 h-4 text-gray-600" />
            )}
            <div className="text-left">
              <div className="text-sm">{layer.name}</div>
              <div className="text-xs text-gray-500">{layer.description}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
