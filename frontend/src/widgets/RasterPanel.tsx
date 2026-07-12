import { useRef, useState } from 'react';
import { Images, Loader2, Upload, FileJson, Archive, RefreshCw } from 'lucide-react';
import { rasterApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

export default function RasterPanel() {
  const [loading, setLoading] = useState(false);
  const [filePath, setFilePath] = useState<string | null>(null);
  const [info, setInfo] = useState<Record<string, unknown> | null>(null);
  const [cogPath, setCogPath] = useState<string | null>(null);
  const [importSummary, setImportSummary] = useState<string | null>(null);
  const tiffRef = useRef<HTMLInputElement>(null);
  const shpRef = useRef<HTMLInputElement>(null);
  const geojsonRef = useRef<HTMLInputElement>(null);
  const { showNotification } = useUIStore();
  const { addAnalysisLayer } = useMapStore();

  const addRasterTiles = (path: string) => {
    const token = localStorage.getItem('access_token');
    const auth = token ? `token=${encodeURIComponent(token)}` : '';
    const base = `${window.location.origin}/api/v1/raster/tiles/{z}/{x}/{y}.png`;
    const qs = `file_path=${encodeURIComponent(path)}${auth ? `&${auth}` : ''}`;
    addAnalysisLayer(`${base}?${qs}`);
  };

  const handleUpload = async (file: File) => {
    setLoading(true);
    setImportSummary(null);
    try {
      const { data } = await rasterApi.upload(file);
      setFilePath(data.file_path);
      setInfo(data.info ?? null);
      setCogPath(null);
      if (data.file_path) {
        addRasterTiles(data.file_path);
      }
      showNotification('GeoTIFF uploaded', 'success');
    } catch {
      showNotification('Upload failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleConvertCog = async () => {
    if (!filePath) {
      showNotification('Upload a GeoTIFF first', 'error');
      return;
    }
    setLoading(true);
    try {
      const { data } = await rasterApi.convertCog(filePath);
      setCogPath(data.cog_path);
      if (data.cog_path) {
        addRasterTiles(data.cog_path);
      }
      showNotification('Converted to COG', 'success');
    } catch {
      showNotification('COG conversion failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleShapefile = async (file: File) => {
    setLoading(true);
    try {
      const { data } = await rasterApi.importShapefile(file);
      setImportSummary(`Shapefile: ${data.feature_count ?? 0} feature(s)`);
      showNotification(`Imported ${data.feature_count ?? 0} features`, 'success');
    } catch {
      showNotification('Shapefile import failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleGeojson = async (file: File) => {
    setLoading(true);
    try {
      const { data } = await rasterApi.importGeojson(file);
      setImportSummary(`GeoJSON: ${data.feature_count ?? 0} feature(s)`);
      showNotification(`Imported ${data.feature_count ?? 0} features`, 'success');
    } catch {
      showNotification('GeoJSON import failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <Images className="w-4 h-4" /> Raster Tools
      </h3>

      <div className="space-y-2">
        <label className="btn-primary w-full flex items-center justify-center gap-2 text-sm cursor-pointer">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          Upload GeoTIFF
          <input
            ref={tiffRef}
            type="file"
            accept=".tif,.tiff,.geotiff"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleUpload(file);
              e.target.value = '';
            }}
          />
        </label>

        <button
          onClick={() => void handleConvertCog()}
          disabled={loading || !filePath}
          className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
        >
          <RefreshCw className="w-4 h-4" /> Convert to COG
        </button>

        <label className="btn-secondary w-full flex items-center justify-center gap-2 text-sm cursor-pointer">
          <Archive className="w-4 h-4" /> Import Shapefile ZIP
          <input
            ref={shpRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleShapefile(file);
              e.target.value = '';
            }}
          />
        </label>

        <label className="btn-secondary w-full flex items-center justify-center gap-2 text-sm cursor-pointer">
          <FileJson className="w-4 h-4" /> Import GeoJSON
          <input
            ref={geojsonRef}
            type="file"
            accept=".geojson,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleGeojson(file);
              e.target.value = '';
            }}
          />
        </label>
      </div>

      {(filePath || cogPath || info || importSummary) && (
        <div className="panel p-3 space-y-1 text-xs">
          {filePath && (
            <div>
              <span className="text-gray-500">File: </span>
              <span className="font-mono break-all text-gray-300">{filePath}</span>
            </div>
          )}
          {cogPath && (
            <div>
              <span className="text-gray-500">COG: </span>
              <span className="font-mono break-all text-gray-300">{cogPath}</span>
            </div>
          )}
          {info && (
            <div className="text-gray-400 space-y-0.5 pt-1">
              {'width' in info && (
                <div>
                  Size: {String(info.width)} × {String(info.height)}
                </div>
              )}
              {'count' in info && <div>Bands: {String(info.count)}</div>}
              {'crs' in info && <div>CRS: {String(info.crs)}</div>}
            </div>
          )}
          {importSummary && <div className="text-earth-400 pt-1">{importSummary}</div>}
        </div>
      )}
    </div>
  );
}
