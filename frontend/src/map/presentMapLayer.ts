/**
 * Permanent Host Shell map-presentation contract.
 *
 * Plugins never touch Leaflet. They declare `map_presentation` in tool-meta
 * (or call a host compute method that already knows the mode). The Host Shell
 * alone decides tiles vs ImageOverlay, z-order, swipe, and scene visibility.
 *
 * Do NOT add per-tool presentation forks in WorkspacePage — extend this module.
 */

import {
  useWorkflowStore,
  type MapOverlay,
} from '../store/workflowStore';

/** Frozen presentation modes — new tools must pick one; do not invent ad-hoc UI. */
export const MAP_PRESENTATION_MODES = [
  /** Natural/visual products that match Eye-On TCI — sharp XYZ on the applied layer. */
  'prefer_scene_tiles',
  /** Processed rasters (FCC, indices, change, classify) — soft PNG + swipe compare. */
  'processed_preview',
  /** Detections / outlines — geojson only; keep scene tiles visible. */
  'vector_geojson',
] as const;

export type MapPresentationMode = (typeof MAP_PRESENTATION_MODES)[number];

/** Built-in tool → presentation (tool-meta.map_presentation must match). */
export const TOOL_MAP_PRESENTATION: Record<string, MapPresentationMode> = {
  optical_true_color: 'prefer_scene_tiles',
  true_color: 'prefer_scene_tiles',
  false_color_infrared: 'processed_preview',
  false_color: 'processed_preview',
};

export function resolveMapPresentation(
  toolOrPreset: string | null | undefined,
  explicit?: MapPresentationMode | string | null,
): MapPresentationMode {
  if (
    explicit &&
    (MAP_PRESENTATION_MODES as readonly string[]).includes(explicit)
  ) {
    return explicit as MapPresentationMode;
  }
  const key = (toolOrPreset || '').trim();
  if (key && TOOL_MAP_PRESENTATION[key]) {
    return TOOL_MAP_PRESENTATION[key];
  }
  return 'processed_preview';
}

export type PresentMapLayerArgs = {
  id: string;
  kind: MapOverlay['kind'];
  sceneId?: string;
  label: string;
  /** Soft PNG / data-URL kept for GeoTIFF export (and drawn when no tiles). */
  url: string;
  bounds: MapOverlay['bounds'];
  footprint?: MapOverlay['footprint'];
  opacity?: number;
  geojson?: MapOverlay['geojson'];
  presentation: MapPresentationMode;
  /** Optional tile template; prefer_scene_tiles falls back to active scene tiles. */
  tileUrl?: string;
  /** Hide other overlays of this kind for the same scene before upsert. */
  hideSiblingKinds?: boolean;
};

export type PresentMapLayerResult = {
  usedSharpTiles: boolean;
  swipeEnabled: boolean;
  messageSuffix: string;
};

/**
 * Apply one analysis/composite layer under the permanent presentation rules.
 */
export function presentMapLayer(args: PresentMapLayerArgs): PresentMapLayerResult {
  const store = useWorkflowStore.getState();
  const opacity = args.opacity ?? Math.max(store.layerOpacity, 0.85);
  const scene =
    args.sceneId != null
      ? store.overlays.find(
          (o) => o.kind === 'scene' && o.sceneId === args.sceneId,
        )
      : undefined;

  if (args.hideSiblingKinds !== false && args.sceneId) {
    for (const o of store.overlays) {
      if (o.sceneId !== args.sceneId) continue;
      if (o.id === args.id) continue;
      if (o.kind === args.kind || o.id.startsWith(`${args.kind}-`)) {
        if (o.visible !== false) store.setOverlayVisible(o.id, false);
      }
    }
  }

  const sharpTileUrl =
    args.presentation === 'prefer_scene_tiles'
      ? args.tileUrl || scene?.tileUrl
      : args.presentation === 'processed_preview'
        ? undefined
        : args.tileUrl;

  store.upsertOverlay({
    id: args.id,
    kind: args.kind,
    sceneId: args.sceneId,
    url: args.url,
    ...(sharpTileUrl ? { tileUrl: sharpTileUrl } : {}),
    bounds: args.bounds,
    footprint: args.footprint ?? null,
    opacity,
    label: args.label,
    visible: true,
    ...(args.geojson != null ? { geojson: args.geojson } : {}),
  });

  if (args.presentation === 'prefer_scene_tiles' && sharpTileUrl && scene) {
    const s = useWorkflowStore.getState();
    const rest = s.overlays.filter((o) => o.id !== args.id && o.id !== scene.id);
    const layer = s.overlays.find((o) => o.id === args.id);
    if (layer) {
      useWorkflowStore.setState({
        overlays: [
          ...rest,
          { ...scene, visible: false },
          { ...layer, visible: true, tileUrl: sharpTileUrl },
        ],
      });
    }
    store.setMapChrome({ swipe: false });
    return {
      usedSharpTiles: true,
      swipeEnabled: false,
      messageSuffix: 'map shows sharp Eye-On tiles (not the soft preview)',
    };
  }

  if (args.presentation === 'processed_preview') {
    if (scene) store.setOverlayVisible(scene.id, true);
    // Ensure soft layer is on top of scene for swipe compare
    const s = useWorkflowStore.getState();
    if (scene) {
      const rest = s.overlays.filter((o) => o.id !== args.id && o.id !== scene.id);
      const layer = s.overlays.find((o) => o.id === args.id);
      const sc = s.overlays.find((o) => o.id === scene.id);
      if (layer && sc) {
        useWorkflowStore.setState({
          overlays: [...rest, { ...sc, visible: true }, { ...layer, visible: true }],
        });
      }
    }
    store.setMapChrome({ swipe: true });
    return {
      usedSharpTiles: false,
      swipeEnabled: true,
      messageSuffix: 'soft preview on map — use Swipe / Layers to compare',
    };
  }

  // vector_geojson
  if (scene) store.setOverlayVisible(scene.id, true);
  store.setMapChrome({ swipe: false });
  return {
    usedSharpTiles: false,
    swipeEnabled: false,
    messageSuffix: 'vector result on map',
  };
}

export type ClearMapLayerArgs = {
  id?: string;
  ids?: string[];
  /** Case-insensitive label substring match (legacy true-color clear). */
  labelIncludes?: string;
  restoreScenes?: boolean;
};

/** Hide presented layer(s) and optionally restore Eye-On scene tiles. */
export function clearMapLayer(args: ClearMapLayerArgs): void {
  const store = useWorkflowStore.getState();
  const idSet = new Set<string>([
    ...(args.id ? [args.id] : []),
    ...(args.ids || []),
  ]);
  const needle = (args.labelIncludes || '').toLowerCase();

  for (const o of store.overlays) {
    const byId = idSet.has(o.id);
    const byLabel =
      needle.length > 0 && (o.label || '').toLowerCase().includes(needle);
    if (byId || byLabel) {
      store.setOverlayVisible(o.id, false);
    }
  }
  if (args.restoreScenes !== false) {
    for (const o of store.overlays) {
      if (o.kind === 'scene') store.setOverlayVisible(o.id, true);
    }
  }
  store.setMapChrome({ swipe: false });
}
