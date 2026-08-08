import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ImagePlus,
  Layers,
  Loader2,
  MapPin,
  Pentagon,
  Play,
  Search,
  Spline,
  Upload,
  Wrench,
  X,
} from 'lucide-react';
import { offlineApi } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import { useStackStore } from '@/store/stackStore';
import { useMapStore } from '@/store/mapStore';
import { useVectorStore } from '@/store/vectorStore';

const RASTER_ACCEPT =
  '.tif,.tiff,.geotiff,.cog,.jp2,.j2k,.jpg,.jpeg,.png,.bmp,.webp,.gif,.img,.nc,.hdf,.h5,.hdf5,.asc,.bil,.vrt';
const VECTOR_ACCEPT = '.geojson,.json,.zip,.kml,.kmz,.gpx,.gml,.shp';

interface GisTool {
  id: string;
  name: string;
  category: string;
  description: string;
}

interface Category {
  name: string;
  count: number;
}

export default function LeftSidebar() {
  const [tools, setTools] = useState<GisTool[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [total, setTotal] = useState(148);
  const [category, setCategory] = useState('');
  const [q, setQ] = useState('');
  const [toolsLoading, setToolsLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [rasterAccept, setRasterAccept] = useState(RASTER_ACCEPT);
  const [vectorAccept, setVectorAccept] = useState(VECTOR_ACCEPT);

  // Raster metadata modal
  const [rasterFile, setRasterFile] = useState<File | null>(null);
  const [placeName, setPlaceName] = useState('');
  const [acquisitionDate, setAcquisitionDate] = useState('');
  const [uploading, setUploading] = useState(false);

  const rasterRef = useRef<HTMLInputElement>(null);
  const vectorRef = useRef<HTMLInputElement>(null);

  const { showNotification, setActivePanel } = useUIStore();
  const { loadStacks, setActiveStack, activeStack, sliderIndex } = useStackStore();
  const { addAnalysisLayer, flyTo } = useMapStore();
  const { addGeoJsonLayer, layers: vectorLayers } = useVectorStore();

  const activeImage = activeStack?.images?.[sliderIndex];
  const activePath =
    activeImage?.working_path ||
    activeImage?.file_path ||
    (activeImage?.metadata?.working_path as string | undefined);

  useEffect(() => {
    void offlineApi.formats().then(({ data }) => {
      if (data?.accept) setRasterAccept(data.accept);
    }).catch(() => undefined);
    void offlineApi.vectorFormats().then(({ data }) => {
      if (data?.accept) setVectorAccept(data.accept);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setToolsLoading(true);
      try {
        const { data } = await offlineApi.tools({
          category: category || undefined,
          q: q || undefined,
        });
        if (cancelled) return;
        setTools(data.tools || []);
        setCategories(data.categories || []);
        setTotal(data.total || 148);
      } catch {
        if (!cancelled) showNotification('Failed to load toolbox', 'error');
      } finally {
        if (!cancelled) setToolsLoading(false);
      }
    };
    const t = setTimeout(() => void load(), q ? 180 : 0);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [category, q, showNotification]);

  const grouped = useMemo(() => {
    const map = new Map<string, GisTool[]>();
    for (const tool of tools) {
      const list = map.get(tool.category) || [];
      list.push(tool);
      map.set(tool.category, list);
    }
    return [...map.entries()];
  }, [tools]);

  const submitRaster = async () => {
    if (!rasterFile) return;
    if (!placeName.trim()) {
      showNotification('Place name is required', 'error');
      return;
    }
    if (!acquisitionDate) {
      showNotification('Acquisition date is compulsory', 'error');
      return;
    }
    setUploading(true);
    try {
      const { data } = await offlineApi.uploadToStack(rasterFile, {
        place_name: placeName.trim(),
        acquisition_date: acquisitionDate,
      });
      await loadStacks();
      setActiveStack(data.stack);
      const tilePath = data.working_path || data.file_path;
      if (tilePath) {
        addAnalysisLayer(
          `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(tilePath)}`,
        );
      }
      if (data.stack?.longitude != null && data.stack?.latitude != null) {
        flyTo(data.stack.longitude, data.stack.latitude, 250000);
      }
      showNotification(`Raster uploaded (${data.format || 'image'})`, 'success');
      setRasterFile(null);
      setPlaceName('');
      setAcquisitionDate('');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Raster upload failed';
      showNotification(String(detail), 'error');
    } finally {
      setUploading(false);
    }
  };

  const handleVectorUpload = async (file: File) => {
    setUploading(true);
    try {
      const { data } = await offlineApi.uploadVector(file);
      addGeoJsonLayer(file.name, data.geojson, {
        feature_count: data.feature_count,
        geometry_counts: data.geometry_counts,
        bbox: data.bbox,
        original_format: data.original_format,
        path: data.path,
      });
      const gc = data.geometry_counts || {};
      const parts = [
        gc.Point || gc.MultiPoint ? `${(gc.Point || 0) + (gc.MultiPoint || 0)} pts` : null,
        gc.LineString || gc.MultiLineString
          ? `${(gc.LineString || 0) + (gc.MultiLineString || 0)} lines`
          : null,
        gc.Polygon || gc.MultiPolygon
          ? `${(gc.Polygon || 0) + (gc.MultiPolygon || 0)} polys`
          : null,
      ].filter(Boolean);
      showNotification(
        `Vector loaded: ${data.feature_count} feature(s)${parts.length ? ` (${parts.join(', ')})` : ''}`,
        'success',
      );
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Vector upload failed';
      showNotification(String(detail), 'error');
    } finally {
      setUploading(false);
    }
  };

  const runTool = async (tool: GisTool) => {
    setRunning(tool.id);
    try {
      const params: Record<string, unknown> = {};
      if (activePath && !String(activePath).startsWith('demo://')) {
        params.file_path = activePath;
        params.working_path = activePath;
      }
      const { data } = await offlineApi.runTool(tool.id, params);
      const msg =
        data.message ||
        (data.stats ? JSON.stringify(data.stats) : data.ok ? 'Completed' : data.error);
      showNotification(`${tool.name}: ${msg}`, data.ok ? 'success' : 'error');
    } catch {
      showNotification(`Failed: ${tool.name}`, 'error');
    } finally {
      setRunning(null);
    }
  };

  return (
    <aside className="absolute top-4 left-4 bottom-4 z-20 w-[19.5rem] flex flex-col gap-2 animate-slide-in">
      <div className="panel p-3 space-y-2 shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-[0.2em] text-sateye-teal">
            Data
          </h2>
          <button
            type="button"
            onClick={() => setActivePanel('layers')}
            className="text-[10px] text-sateye-mist/50 hover:text-sateye-teal inline-flex items-center gap-1"
            title="Open layers panel"
          >
            <Layers className="w-3 h-3" /> Layers
          </button>
        </div>

        <button
          type="button"
          disabled={uploading}
          onClick={() => rasterRef.current?.click()}
          className="btn-primary w-full flex items-center justify-center gap-2 text-sm"
        >
          {uploading && rasterFile ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ImagePlus className="w-4 h-4" />
          )}
          Add Raster Data
        </button>
        <input
          ref={rasterRef}
          type="file"
          accept={rasterAccept}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0] || null;
            setRasterFile(file);
            e.target.value = '';
          }}
        />

        <button
          type="button"
          disabled={uploading}
          onClick={() => vectorRef.current?.click()}
          className="btn-secondary w-full flex items-center justify-center gap-2 text-sm border border-sateye-teal/25"
        >
          {uploading && !rasterFile ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Upload className="w-4 h-4" />
          )}
          Add Vector Data
        </button>
        <input
          ref={vectorRef}
          type="file"
          accept={vectorAccept}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleVectorUpload(file);
            e.target.value = '';
          }}
        />

        <div className="flex items-center gap-2 text-[10px] text-sateye-mist/40 pt-0.5">
          <MapPin className="w-3 h-3 text-amber-300/80" /> Point
          <Spline className="w-3 h-3 text-sky-400/80" /> Line
          <Pentagon className="w-3 h-3 text-sateye-teal/80" /> Polygon
        </div>

        {vectorLayers.length > 0 && (
          <div className="text-[10px] text-sateye-mist/50">
            Loaded vectors: {vectorLayers.length}
          </div>
        )}
      </div>

      {/* Raster metadata prompt */}
      {rasterFile && (
        <div className="panel p-3 space-y-2 shrink-0 border-sateye-teal/30">
          <div className="flex items-center justify-between">
            <div className="text-xs text-sateye-mist/70 truncate pr-2">{rasterFile.name}</div>
            <button type="button" onClick={() => setRasterFile(null)} className="text-sateye-mist/40">
              <X className="w-4 h-4" />
            </button>
          </div>
          <input
            className="input-field text-sm"
            placeholder="Place name *"
            value={placeName}
            onChange={(e) => setPlaceName(e.target.value)}
          />
          <div>
            <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
              Acquisition date * compulsory
            </label>
            <input
              type="date"
              className="input-field text-sm mt-1"
              value={acquisitionDate}
              onChange={(e) => setAcquisitionDate(e.target.value)}
            />
          </div>
          <button
            type="button"
            disabled={uploading}
            onClick={() => void submitRaster()}
            className="btn-primary w-full text-sm flex items-center justify-center gap-2"
          >
            {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            Upload raster
          </button>
        </div>
      )}

      {/* Toolbox */}
      <div className="panel p-3 flex-1 min-h-0 flex flex-col">
        <div className="flex items-center justify-between mb-2 shrink-0">
          <h2 className="text-xs font-semibold uppercase tracking-[0.2em] text-sateye-teal inline-flex items-center gap-1.5">
            <Wrench className="w-3.5 h-3.5" />
            Toolbox
          </h2>
          <span className="text-[10px] text-sateye-mist/45">{total} tools</span>
        </div>

        <div className="relative mb-2 shrink-0">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-sateye-mist/35" />
          <input
            className="input-field text-sm pl-8"
            placeholder="Search tools…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap gap-1 mb-2 shrink-0 max-h-16 overflow-y-auto">
          <button
            type="button"
            onClick={() => setCategory('')}
            className={`text-[10px] px-1.5 py-0.5 rounded ${
              !category ? 'bg-sateye-teal/20 text-sateye-teal' : 'bg-sateye-panel text-sateye-mist/55'
            }`}
          >
            All
          </button>
          {categories.map((c) => (
            <button
              key={c.name}
              type="button"
              onClick={() => setCategory(c.name)}
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                category === c.name
                  ? 'bg-sateye-teal/20 text-sateye-teal'
                  : 'bg-sateye-panel text-sateye-mist/55'
              }`}
            >
              {c.name} ({c.count})
            </button>
          ))}
        </div>

        {toolsLoading ? (
          <div className="flex-1 flex items-center justify-center text-sateye-mist/40">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-1 space-y-3">
            {grouped.map(([cat, list]) => (
              <div key={cat}>
                <div className="text-[10px] uppercase tracking-[0.18em] text-sateye-mist/40 mb-1 sticky top-0 bg-sateye-ink/90 py-0.5">
                  {cat}
                </div>
                <div className="space-y-0.5">
                  {list.map((tool) => (
                    <button
                      key={tool.id}
                      type="button"
                      onClick={() => void runTool(tool)}
                      disabled={running === tool.id}
                      className="w-full text-left px-2 py-1.5 rounded hover:bg-sateye-panel/80 flex items-start gap-2 group"
                      title={tool.description}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium truncate">{tool.name}</div>
                        <div className="text-[10px] text-sateye-mist/40 truncate">
                          {tool.description}
                        </div>
                      </div>
                      <span className="shrink-0 mt-0.5 text-sateye-teal opacity-70 group-hover:opacity-100">
                        {running === tool.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Play className="w-3.5 h-3.5" />
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
