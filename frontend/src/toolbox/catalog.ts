/** Light Explorer toolbox catalog — maps UI tools to runnable actions. */

export type ToolboxId =
  | 'navigation'
  | 'layers'
  | 'image'
  | 'ai'
  | 'change'
  | 'maritime'
  | 'aviation'
  | 'terrain'
  | 'gis'
  | 'measure';

/** Domain tools hidden for standard EO satellites (Sentinel / Landsat / MODIS, etc.). */
export const EO_HIDDEN_TOOLBOXES: ToolboxId[] = [
  'ai',
  'change',
  'maritime',
  'aviation',
];

/** True for catalog satellites that use standard EO imagery toolboxes only. */
export function isStandardEoSatellite(name?: string | null): boolean {
  if (!name) return false;
  const n = name.toUpperCase().replace(/_/g, '-');
  return (
    n.includes('SENTINEL') ||
    n.includes('LANDSAT') ||
    n.includes('MODIS') ||
    n.includes('TERRA') ||
    n.includes('AQUA') ||
    n.includes('SMOS') ||
    n.includes('ENVISAT') ||
    n.includes('COP-DEM') ||
    n.includes('GLOBAL-MOSAIC')
  );
}

export type ToolAction =
  | { type: 'map'; mode: string }
  | { type: 'toggle'; key: string }
  | { type: 'index'; index: string }
  | { type: 'terrain'; product: string }
  | { type: 'detection'; task: string }
  | { type: 'change'; mode: string }
  | { type: 'gis'; op: string }
  | { type: 'measure'; mode: string }
  | { type: 'layer'; op: string }
  | { type: 'process'; op: string };

export interface ToolboxTool {
  id: string;
  label: string;
  action: ToolAction;
  hint?: string;
  /** Prefer a visible scene when running on imagery */
  needsScene?: boolean;
}

export interface ToolboxDef {
  id: ToolboxId;
  title: string;
  blurb: string;
  tools: ToolboxTool[];
}

export const TOOLBOXES: ToolboxDef[] = [
  {
    id: 'navigation',
    title: 'Map Navigation',
    blurb: 'Pan, zoom, views, chrome & comparison',
    tools: [
      { id: 'pan', label: 'Pan', action: { type: 'map', mode: 'navigate' } },
      { id: 'zoom_in', label: 'Zoom In', action: { type: 'map', mode: 'zoom-in' } },
      { id: 'zoom_out', label: 'Zoom Out', action: { type: 'map', mode: 'zoom-out' } },
      { id: 'rotate', label: 'Rotate', action: { type: 'toggle', key: 'rotate' } },
      { id: 'view_2d', label: '2D View', action: { type: 'toggle', key: 'view2d' } },
      { id: 'view_3d', label: '3D Globe', action: { type: 'toggle', key: 'view3d' } },
      { id: 'terrain_on', label: 'Terrain On/Off', action: { type: 'toggle', key: 'terrainRelief' } },
      { id: 'fullscreen', label: 'Full Screen', action: { type: 'toggle', key: 'fullscreen' } },
      { id: 'split', label: 'Split View', action: { type: 'toggle', key: 'splitView' } },
      { id: 'swipe', label: 'Swipe Comparison', action: { type: 'toggle', key: 'swipe' } },
      { id: 'sync', label: 'Synchronize Maps', action: { type: 'toggle', key: 'syncMaps' } },
      { id: 'minimap', label: 'Mini Map', action: { type: 'toggle', key: 'miniMap' } },
      { id: 'compass', label: 'Compass / North Arrow', action: { type: 'toggle', key: 'compass' } },
      { id: 'scale', label: 'Scale Bar', action: { type: 'toggle', key: 'scaleBar' } },
      { id: 'coords', label: 'Coordinates', action: { type: 'toggle', key: 'coordinates' } },
      { id: 'grid', label: 'Map Grid', action: { type: 'toggle', key: 'grid' } },
      { id: 'bookmarks', label: 'Bookmarks', action: { type: 'toggle', key: 'bookmarks' } },
    ],
  },
  {
    id: 'layers',
    title: 'Layer Manager',
    blurb: 'Drag to reorder · DEM base height · scene & analytics layers',
    tools: [
      { id: 'add_layer', label: 'Add Layer', action: { type: 'layer', op: 'add' } },
      { id: 'remove_layer', label: 'Remove Layer', action: { type: 'layer', op: 'remove' } },
      { id: 'opacity', label: 'Opacity Slider', action: { type: 'layer', op: 'opacity' } },
      { id: 'ordering', label: 'Layer Ordering', action: { type: 'layer', op: 'order' } },
      { id: 'rename', label: 'Rename Layer', action: { type: 'layer', op: 'rename' } },
      { id: 'duplicate', label: 'Duplicate Layer', action: { type: 'layer', op: 'duplicate' } },
      { id: 'styles', label: 'Layer Styles', action: { type: 'layer', op: 'styles' } },
      { id: 'labels', label: 'Labels', action: { type: 'layer', op: 'labels' } },
      { id: 'transparency', label: 'Transparency', action: { type: 'layer', op: 'transparency' } },
      { id: 'blend', label: 'Blend Modes', action: { type: 'layer', op: 'blend' } },
    ],
  },
  {
    id: 'image',
    title: 'Image Processing',
    blurb: 'True/false color, indices & raster adjustments',
    tools: [
      { id: 'true_color', label: 'True Color', action: { type: 'process', op: 'true_color' }, needsScene: true },
      { id: 'false_color', label: 'False Color', action: { type: 'process', op: 'false_color' }, needsScene: true },
      { id: 'ndvi', label: 'NDVI', action: { type: 'index', index: 'NDVI' }, needsScene: true },
      { id: 'ndwi', label: 'NDWI', action: { type: 'index', index: 'NDWI' }, needsScene: true },
      { id: 'ndbi', label: 'NDBI', action: { type: 'index', index: 'NDBI' }, needsScene: true },
      { id: 'savi', label: 'SAVI', action: { type: 'index', index: 'SAVI' }, needsScene: true },
      { id: 'bsi', label: 'BSI', action: { type: 'index', index: 'BSI' }, needsScene: true },
      { id: 'evi', label: 'EVI', action: { type: 'index', index: 'EVI' }, needsScene: true },
      { id: 'ndmi', label: 'NDMI', action: { type: 'index', index: 'NDMI' }, needsScene: true },
      { id: 'nbr', label: 'Burn Index', action: { type: 'index', index: 'NBR' }, needsScene: true },
      { id: 'hist', label: 'Histogram Stretch', action: { type: 'process', op: 'histogram' }, needsScene: true },
      { id: 'brightness', label: 'Brightness', action: { type: 'process', op: 'brightness' }, needsScene: true },
      { id: 'contrast', label: 'Contrast', action: { type: 'process', op: 'contrast' }, needsScene: true },
      { id: 'gamma', label: 'Gamma', action: { type: 'process', op: 'gamma' }, needsScene: true },
      { id: 'sharpen', label: 'Sharpen', action: { type: 'process', op: 'sharpen' }, needsScene: true },
      { id: 'denoise', label: 'Denoise', action: { type: 'process', op: 'denoise' }, needsScene: true },
      { id: 'cloud_mask', label: 'Cloud Mask', action: { type: 'detection', task: 'cloud_mask' }, needsScene: true },
      { id: 'mosaic', label: 'Image Mosaic', action: { type: 'process', op: 'mosaic' }, needsScene: true },
      { id: 'clip', label: 'Clip Raster', action: { type: 'gis', op: 'clip' } },
      { id: 'reproject', label: 'Reproject', action: { type: 'process', op: 'reproject' } },
      { id: 'resample', label: 'Resample', action: { type: 'process', op: 'resample' } },
    ],
  },
  {
    id: 'ai',
    title: 'AI Detection',
    blurb: 'Object & land-cover detection on imagery',
    tools: [
      { id: 'building_detection', label: 'Building Detection', action: { type: 'detection', task: 'building_detection' }, needsScene: true },
      { id: 'road_extraction', label: 'Road Extraction', action: { type: 'detection', task: 'road_extraction' }, needsScene: true },
      { id: 'bridge_detection', label: 'Bridge Detection', action: { type: 'detection', task: 'bridge_detection' }, needsScene: true },
      { id: 'airport_mapping', label: 'Airport Mapping', action: { type: 'detection', task: 'airport_mapping' }, needsScene: true },
      { id: 'runway_detection', label: 'Runway Detection', action: { type: 'detection', task: 'runway_detection' }, needsScene: true },
      { id: 'port_mapping', label: 'Port Mapping', action: { type: 'detection', task: 'port_mapping' }, needsScene: true },
      { id: 'harbor_detection', label: 'Harbor Detection', action: { type: 'detection', task: 'harbor_detection' }, needsScene: true },
      { id: 'ship_detection', label: 'Ship Detection', action: { type: 'detection', task: 'ship_detection' }, needsScene: true },
      { id: 'aircraft_detection', label: 'Aircraft Detection', action: { type: 'detection', task: 'aircraft_detection' }, needsScene: true },
      { id: 'railway_detection', label: 'Railway Detection', action: { type: 'detection', task: 'railway_detection' }, needsScene: true },
      { id: 'powerline', label: 'Powerline Corridor Mapping', action: { type: 'detection', task: 'powerline_corridor_mapping' }, needsScene: true },
      { id: 'solar', label: 'Solar Farm Detection', action: { type: 'detection', task: 'solar_farm_detection' }, needsScene: true },
      { id: 'wind', label: 'Wind Farm Detection', action: { type: 'detection', task: 'wind_farm_detection' }, needsScene: true },
      { id: 'construction', label: 'Construction Site Detection', action: { type: 'detection', task: 'construction_site_detection' }, needsScene: true },
      { id: 'urban_exp', label: 'Urban Expansion Detection', action: { type: 'detection', task: 'urban_expansion_detection' }, needsScene: true },
      { id: 'veg_class', label: 'Vegetation Classification', action: { type: 'detection', task: 'vegetation_classification' }, needsScene: true },
      { id: 'flood', label: 'Flood Detection', action: { type: 'detection', task: 'flood_detection' }, needsScene: true },
      { id: 'burn', label: 'Burn Scar Detection', action: { type: 'detection', task: 'burn_scar_detection' }, needsScene: true },
      { id: 'water', label: 'Water Body Extraction', action: { type: 'detection', task: 'water_body_extraction' }, needsScene: true },
      { id: 'lulc', label: 'Land Cover Classification', action: { type: 'detection', task: 'land_cover_classification' }, needsScene: true },
      { id: 'conf', label: 'Confidence Heatmap', action: { type: 'detection', task: 'confidence_heatmap' }, needsScene: true },
      { id: 'manual', label: 'Manual Verification Mode', action: { type: 'toggle', key: 'manualVerify' } },
    ],
  },
  {
    id: 'change',
    title: 'Change Detection',
    blurb: 'Compare dates and thematic change on scenes',
    tools: [
      { id: 'compare_two', label: 'Compare Two Dates', action: { type: 'change', mode: 'two' }, needsScene: true },
      { id: 'compare_multi', label: 'Compare Multiple Dates', action: { type: 'change', mode: 'multi' }, needsScene: true },
      { id: 'urban_growth', label: 'Urban Growth', action: { type: 'change', mode: 'urban' }, needsScene: true },
      { id: 'forest_loss', label: 'Forest Loss', action: { type: 'change', mode: 'forest_loss' }, needsScene: true },
      { id: 'forest_gain', label: 'Forest Gain', action: { type: 'change', mode: 'forest_gain' }, needsScene: true },
      { id: 'ag_change', label: 'Agricultural Change', action: { type: 'change', mode: 'agriculture' }, needsScene: true },
      { id: 'water_change', label: 'Water Change', action: { type: 'change', mode: 'water' }, needsScene: true },
      { id: 'river_change', label: 'River Course Change', action: { type: 'change', mode: 'river' }, needsScene: true },
      { id: 'coastal', label: 'Coastal Change', action: { type: 'change', mode: 'coastal' }, needsScene: true },
      { id: 'shoreline', label: 'Shoreline Change', action: { type: 'change', mode: 'shoreline' }, needsScene: true },
      { id: 'flood_change', label: 'Flood Change', action: { type: 'change', mode: 'flood' }, needsScene: true },
      { id: 'burn_change', label: 'Burn Area Change', action: { type: 'change', mode: 'burn' }, needsScene: true },
      { id: 'construction_change', label: 'Construction Change', action: { type: 'change', mode: 'construction' }, needsScene: true },
      { id: 'infra_growth', label: 'Infrastructure Growth', action: { type: 'change', mode: 'infra' }, needsScene: true },
      { id: 'auto_report', label: 'Automatic Change Report', action: { type: 'change', mode: 'report' }, needsScene: true },
      { id: 'time_slider', label: 'Time Slider', action: { type: 'toggle', key: 'timeSlider' } },
      { id: 'change_stats', label: 'Change Statistics', action: { type: 'change', mode: 'stats' }, needsScene: true },
    ],
  },
  {
    id: 'maritime',
    title: 'Maritime Analytics',
    blurb: 'Ships, ports, ocean overlays & coasts',
    tools: [
      { id: 'ship_sar', label: 'Ship Detection (SAR)', action: { type: 'detection', task: 'ship_detection_sar' }, needsScene: true },
      { id: 'ship_opt', label: 'Ship Detection (Optical)', action: { type: 'detection', task: 'ship_detection_optical' }, needsScene: true },
      { id: 'vessel_density', label: 'Vessel Density Map', action: { type: 'detection', task: 'vessel_density_map' }, needsScene: true },
      { id: 'port_act', label: 'Port Activity Mapping', action: { type: 'detection', task: 'port_activity_mapping' }, needsScene: true },
      { id: 'anchorage', label: 'Anchorage Detection', action: { type: 'detection', task: 'anchorage_detection' }, needsScene: true },
      { id: 'lanes', label: 'Shipping Lane Visualization', action: { type: 'detection', task: 'shipping_lane_visualization' }, needsScene: true },
      { id: 'oil', label: 'Oil Spill Detection', action: { type: 'detection', task: 'oil_spill_detection' }, needsScene: true },
      { id: 'sst', label: 'Sea Surface Temperature', action: { type: 'detection', task: 'sea_surface_temperature' }, needsScene: true },
      { id: 'chl', label: 'Chlorophyll Overlay', action: { type: 'detection', task: 'chlorophyll_overlay' }, needsScene: true },
      { id: 'wave', label: 'Wave Height Overlay', action: { type: 'detection', task: 'wave_height_overlay' }, needsScene: true },
      { id: 'wind', label: 'Wind Speed Overlay', action: { type: 'detection', task: 'wind_speed_overlay' }, needsScene: true },
      { id: 'erosion', label: 'Coastal Erosion Mapping', action: { type: 'detection', task: 'coastal_erosion_mapping' }, needsScene: true },
      { id: 'tidal', label: 'Tidal Zone Mapping', action: { type: 'detection', task: 'tidal_zone_mapping' }, needsScene: true },
    ],
  },
  {
    id: 'aviation',
    title: 'Air Domain & Aviation',
    blurb: 'Airports, airspace, weather & elevation',
    tools: [
      { id: 'airport_db', label: 'Airport Database', action: { type: 'detection', task: 'airport_database' } },
      { id: 'runway_inv', label: 'Runway Inventory', action: { type: 'detection', task: 'runway_inventory' } },
      { id: 'airport_exp', label: 'Airport Expansion Monitoring', action: { type: 'detection', task: 'airport_expansion_monitoring' }, needsScene: true },
      { id: 'airspace', label: 'Airspace Overlay', action: { type: 'detection', task: 'airspace_overlay' } },
      { id: 'notam', label: 'NOTAM Overlay', action: { type: 'detection', task: 'notam_overlay' } },
      { id: 'wx', label: 'Weather Overlay', action: { type: 'detection', task: 'weather_overlay' } },
      { id: 'terr_aware', label: 'Terrain Awareness', action: { type: 'detection', task: 'terrain_awareness' } },
      { id: 'dem_profile', label: 'DEM Profile', action: { type: 'terrain', product: 'profile' } },
      { id: 'elev_xsect', label: 'Elevation Cross Section', action: { type: 'terrain', product: 'profile' } },
      { id: 'visibility', label: 'Visibility Analysis', action: { type: 'terrain', product: 'viewshed' } },
    ],
  },
  {
    id: 'terrain',
    title: 'Terrain Analysis',
    blurb: 'DEM, hydro, viewshed & surface metrics',
    tools: [
      { id: 'dem', label: 'DEM 3D (under imagery)', action: { type: 'terrain', product: 'dem' } },
      { id: 'hillshade', label: 'Hillshade', action: { type: 'terrain', product: 'hillshade' } },
      { id: 'slope', label: 'Slope', action: { type: 'terrain', product: 'slope' } },
      { id: 'aspect', label: 'Aspect', action: { type: 'terrain', product: 'aspect' } },
      { id: 'contours', label: 'Contours', action: { type: 'terrain', product: 'contour' } },
      { id: 'watershed', label: 'Watershed', action: { type: 'terrain', product: 'watershed' } },
      { id: 'flow_dir', label: 'Flow Direction', action: { type: 'terrain', product: 'flow_direction' } },
      { id: 'flow_acc', label: 'Flow Accumulation', action: { type: 'terrain', product: 'flow_accumulation' } },
      { id: 'tri', label: 'Terrain Ruggedness', action: { type: 'terrain', product: 'ruggedness' } },
      { id: 'profile', label: 'Terrain Profile', action: { type: 'terrain', product: 'profile' } },
      { id: 'cutfill', label: 'Cut/Fill Analysis', action: { type: 'terrain', product: 'cut_fill' } },
      { id: 'viewshed', label: 'Viewshed', action: { type: 'terrain', product: 'viewshed' } },
      { id: 'los', label: 'Line of Sight', action: { type: 'terrain', product: 'line_of_sight' } },
    ],
  },
  {
    id: 'gis',
    title: 'GIS Analysis',
    blurb: 'Vector overlays & spatial operations',
    tools: [
      { id: 'buffer', label: 'Buffer', action: { type: 'gis', op: 'buffer' } },
      { id: 'intersect', label: 'Intersect', action: { type: 'gis', op: 'intersect' } },
      { id: 'union', label: 'Union', action: { type: 'gis', op: 'union' } },
      { id: 'clip', label: 'Clip', action: { type: 'gis', op: 'clip' } },
      { id: 'dissolve', label: 'Dissolve', action: { type: 'gis', op: 'dissolve' } },
      { id: 'merge', label: 'Merge', action: { type: 'gis', op: 'merge' } },
      { id: 'spatial_join', label: 'Spatial Join', action: { type: 'gis', op: 'merge' } },
      { id: 'nearest', label: 'Nearest Neighbor', action: { type: 'gis', op: 'nearest' } },
      { id: 'density', label: 'Density Analysis', action: { type: 'gis', op: 'density' } },
      { id: 'hotspot', label: 'Hotspot Analysis', action: { type: 'gis', op: 'hotspot' } },
      { id: 'thiessen', label: 'Thiessen Polygons', action: { type: 'gis', op: 'thiessen' } },
      { id: 'voronoi', label: 'Voronoi', action: { type: 'gis', op: 'voronoi' } },
      { id: 'hull', label: 'Convex Hull', action: { type: 'gis', op: 'convex_hull' } },
      { id: 'grid', label: 'Grid Generator', action: { type: 'gis', op: 'density' } },
    ],
  },
  {
    id: 'measure',
    title: 'Measurement',
    blurb: 'Distance, area, bearing & coordinates',
    tools: [
      { id: 'distance', label: 'Distance', action: { type: 'measure', mode: 'measure-line' } },
      { id: 'area', label: 'Area', action: { type: 'measure', mode: 'measure-area' } },
      { id: 'perimeter', label: 'Perimeter', action: { type: 'measure', mode: 'measure-area' } },
      { id: 'bearing', label: 'Bearing', action: { type: 'measure', mode: 'measure-line' } },
      { id: 'elevation', label: 'Elevation', action: { type: 'terrain', product: 'profile' } },
      { id: 'volume', label: 'Volume', action: { type: 'terrain', product: 'cut_fill' } },
      { id: 'radius', label: 'Radius', action: { type: 'gis', op: 'buffer' } },
      { id: 'coord_picker', label: 'Coordinate Picker', action: { type: 'measure', mode: 'draw-point' } },
      { id: 'poly_meas', label: 'Polygon Measurement', action: { type: 'measure', mode: 'aoi-poly' } },
      { id: 'line_meas', label: 'Polyline Measurement', action: { type: 'measure', mode: 'measure-line' } },
    ],
  },
];
