import { useEffect, useMemo, useState } from 'react';
import { Loader2, Play, Search, Wrench } from 'lucide-react';
import { offlineApi } from '@/services/api';
import { useUIStore } from '@/store/uiStore';
import { useStackStore } from '@/store/stackStore';

interface GisTool {
  id: string;
  name: string;
  category: string;
  description: string;
  inputs: string[];
  offline: boolean;
}

interface Category {
  name: string;
  count: number;
}

export default function ToolsPanel() {
  const [tools, setTools] = useState<GisTool[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [total, setTotal] = useState(148);
  const [category, setCategory] = useState<string>('');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const { showNotification } = useUIStore();
  const { activeStack, sliderIndex } = useStackStore();
  const activeImage = activeStack?.images?.[sliderIndex];
  const activePath =
    activeImage?.working_path ||
    activeImage?.file_path ||
    (activeImage?.metadata?.working_path as string | undefined);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
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
        if (!cancelled) showNotification('Failed to load GIS tools', 'error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    const t = setTimeout(() => void load(), q ? 200 : 0);
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

  const runTool = async (tool: GisTool) => {
    setRunning(tool.id);
    setResult(null);
    try {
      const params: Record<string, unknown> = {};
      // Pass current slider image so tools work on any uploaded format (normalized server-side)
      if (activePath && !String(activePath).startsWith('demo://')) {
        params.file_path = activePath;
        params.working_path = activePath;
      }
      if (activeImage?.acquisition_date) {
        params.acquisition_date = activeImage.acquisition_date;
      }
      const { data } = await offlineApi.runTool(tool.id, params);
      const msg =
        data.message ||
        (data.stats ? JSON.stringify(data.stats) : data.ok ? 'Completed offline' : data.error);
      setResult(`${tool.name}: ${msg}`);
      showNotification(`${tool.name} executed`, data.ok ? 'success' : 'error');
    } catch {
      showNotification(`Failed to run ${tool.name}`, 'error');
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-sateye-mist/55">
        <span className="inline-flex items-center gap-1.5">
          <Wrench className="w-3.5 h-3.5 text-sateye-teal" />
          {total} offline GIS tools
        </span>
        <span>{tools.length} shown</span>
      </div>

      {activeImage ? (
        <div className="text-[11px] text-sateye-mist/50 bg-sateye-panel/50 rounded px-2 py-1.5">
          Target: <span className="text-sateye-teal">{activeImage.acquisition_date}</span>
          {activeImage.original_format && (
            <span> · {activeImage.original_format}</span>
          )}
          <span className="text-sateye-mist/35"> (any format → tools via GeoTIFF)</span>
        </div>
      ) : (
        <div className="text-[11px] text-sateye-mist/45">
          Upload a dated image (or select a stack) to run tools on it.
        </div>
      )}

      <div className="relative">
        <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-sateye-mist/40" />
        <input
          className="input-field text-sm pl-8"
          placeholder="Search tools…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="flex flex-wrap gap-1">
        <button
          onClick={() => setCategory('')}
          className={`text-[10px] px-2 py-1 rounded border ${
            !category
              ? 'border-sateye-teal/50 bg-sateye-teal/15 text-sateye-teal'
              : 'border-transparent bg-sateye-panel/80 text-sateye-mist/60'
          }`}
        >
          All
        </button>
        {categories.map((c) => (
          <button
            key={c.name}
            onClick={() => setCategory(c.name)}
            className={`text-[10px] px-2 py-1 rounded border ${
              category === c.name
                ? 'border-sateye-teal/50 bg-sateye-teal/15 text-sateye-teal'
                : 'border-transparent bg-sateye-panel/80 text-sateye-mist/60'
            }`}
          >
            {c.name} ({c.count})
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-8 text-sateye-mist/50">
          <Loader2 className="w-5 h-5 animate-spin" />
        </div>
      ) : (
        <div className="space-y-4 max-h-[55vh] overflow-y-auto pr-1">
          {grouped.map(([cat, list]) => (
            <div key={cat}>
              <h4 className="text-[11px] uppercase tracking-[0.2em] text-sateye-mist/45 mb-1.5">
                {cat}
              </h4>
              <div className="space-y-1">
                {list.map((tool) => (
                  <div
                    key={tool.id}
                    className="flex items-start gap-2 p-2 rounded hover:bg-sateye-panel/70 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{tool.name}</div>
                      <div className="text-[11px] text-sateye-mist/45 leading-snug">
                        {tool.description}
                      </div>
                    </div>
                    <button
                      onClick={() => void runTool(tool)}
                      disabled={running === tool.id}
                      className="shrink-0 p-1.5 rounded bg-sateye-teal/15 text-sateye-teal hover:bg-sateye-teal/25"
                      title={`Run ${tool.name}`}
                    >
                      {running === tool.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Play className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {result && (
        <div className="text-[11px] text-sateye-mist/70 bg-sateye-panel/60 p-2 rounded leading-relaxed">
          {result}
        </div>
      )}
    </div>
  );
}
