import { useRef, useState } from 'react';
import { Loader2, Upload, Satellite } from 'lucide-react';
import { offlineApi } from '@/services/api';
import { useStackStore } from '@/store/stackStore';
import { useUIStore } from '@/store/uiStore';
import { useMapStore } from '@/store/mapStore';

export default function UploadPanel() {
  const [loading, setLoading] = useState(false);
  const [placeName, setPlaceName] = useState('');
  const [acquisitionDate, setAcquisitionDate] = useState('');
  const [lastResult, setLastResult] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { showNotification } = useUIStore();
  const { loadStacks, setActiveStack } = useStackStore();
  const { addAnalysisLayer, flyTo } = useMapStore();

  const handleUpload = async (file: File) => {
    if (!placeName.trim()) {
      showNotification('Enter a place name to group images of the same location', 'error');
      return;
    }
    setLoading(true);
    setLastResult(null);
    try {
      const { data } = await offlineApi.uploadToStack(file, {
        place_name: placeName.trim(),
        acquisition_date: acquisitionDate || undefined,
      });
      const stack = data.stack;
      setLastResult(
        `Added to “${stack.name}” — ${stack.image_count} image(s). ` +
          (stack.image_count >= 2
            ? 'Date slider is available at the bottom of the map.'
            : 'Upload more dates of this place to enable the slider.'),
      );
      await loadStacks();
      setActiveStack(stack);
      if (data.file_path) {
        const url =
          `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(data.file_path)}`;
        addAnalysisLayer(url);
      }
      if (stack.longitude != null && stack.latitude != null) {
        flyTo(stack.longitude, stack.latitude, 250000);
      }
      showNotification('Satellite image uploaded offline', 'success');
    } catch {
      showNotification('Upload failed — check GeoTIFF file', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-sateye-mist/60 leading-relaxed">
        SAT EYE runs fully offline. Feed the workspace by uploading satellite images from your PC.
        Images of the same place are stacked so you can scrub dates with the slider.
      </p>

      <div className="space-y-2">
        <label className="text-xs text-sateye-mist/50 uppercase tracking-wider">Place name</label>
        <input
          className="input-field text-sm"
          placeholder="e.g. Nile Delta, Demo Valley"
          value={placeName}
          onChange={(e) => setPlaceName(e.target.value)}
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs text-sateye-mist/50 uppercase tracking-wider">
          Acquisition date (optional)
        </label>
        <input
          type="date"
          className="input-field text-sm"
          value={acquisitionDate}
          onChange={(e) => setAcquisitionDate(e.target.value)}
        />
      </div>

      <label className="btn-primary w-full flex items-center justify-center gap-2 text-sm cursor-pointer">
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
        Upload Satellite Image
        <input
          ref={inputRef}
          type="file"
          accept=".tif,.tiff,.geotiff,.jp2,.img"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleUpload(file);
            e.target.value = '';
          }}
        />
      </label>

      <div className="panel p-3 text-xs text-sateye-mist/55 space-y-1">
        <div className="flex items-center gap-2 text-sateye-teal">
          <Satellite className="w-3.5 h-3.5" />
          Offline feed only
        </div>
        <p>Supported: GeoTIFF / COG. No Copernicus or internet connection is used.</p>
        <p>Tip: upload ~20 dates of the same place to fully exercise the date slider.</p>
      </div>

      {lastResult && (
        <div className="text-xs text-sateye-teal/90 leading-relaxed">{lastResult}</div>
      )}
    </div>
  );
}
