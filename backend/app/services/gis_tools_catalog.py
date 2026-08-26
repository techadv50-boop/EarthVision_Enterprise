"""SAT EYE offline GIS tool catalog — exactly 148 tools for local EO workflows."""

from __future__ import annotations

from typing import Any, TypedDict


class GisTool(TypedDict):
    id: str
    name: str
    category: str
    description: str
    inputs: list[str]
    offline: bool


def _tool(
    id_: str,
    name: str,
    category: str,
    description: str,
    inputs: list[str] | None = None,
) -> GisTool:
    return {
        "id": id_,
        "name": name,
        "category": category,
        "description": description,
        "inputs": inputs or ["raster"],
        "offline": True,
    }


def build_gis_tools() -> list[GisTool]:
    """Build the full SAT EYE offline tool registry (148 tools)."""
    tools: list[GisTool] = []

    # --- Raster (30) ---
    raster = [
        ("clip_raster", "Clip Raster", "Crop raster to AOI or extent"),
        ("resample_raster", "Resample Raster", "Change pixel resolution"),
        ("reproject_raster", "Reproject Raster", "Warp raster to target CRS"),
        ("mosaic_rasters", "Mosaic Rasters", "Merge overlapping rasters"),
        ("raster_calculator", "Raster Calculator", "Band math expressions"),
        ("extract_band", "Extract Band", "Isolate a spectral band"),
        ("stack_bands", "Stack Bands", "Combine bands into multi-band raster"),
        ("composite_rgb", "RGB Composite", "True/false color composite"),
        ("histogram_equalize", "Histogram Equalize", "Enhance contrast"),
        ("stretch_minmax", "Min-Max Stretch", "Linear stretch display"),
        ("stretch_std", "Standard Deviation Stretch", "Std-dev contrast stretch"),
        ("pan_sharpen", "Pansharpen", "Fuse pan + multispectral"),
        ("cloud_mask", "Cloud Mask", "Mask cloudy pixels"),
        ("nodata_fill", "NoData Fill", "Fill missing pixels"),
        ("raster_to_points", "Raster to Points", "Convert cells to point features"),
        ("raster_to_polygons", "Raster to Polygons", "Vectorize classified raster"),
        ("zonal_stats", "Zonal Statistics", "Stats per polygon zone"),
        ("focal_mean", "Focal Mean", "Neighborhood mean filter"),
        ("focal_median", "Focal Median", "Neighborhood median filter"),
        ("focal_std", "Focal StdDev", "Neighborhood standard deviation"),
        ("majority_filter", "Majority Filter", "Mode filter for classification"),
        ("edge_detect", "Edge Detection", "Sobel/Canny edges on raster"),
        ("threshold_binary", "Binary Threshold", "Threshold to binary mask"),
        ("reclassify", "Reclassify", "Remap value ranges"),
        ("raster_info", "Raster Info", "CRS, size, bands, stats"),
        ("cog_convert", "Convert to COG", "Cloud Optimized GeoTIFF"),
        ("tile_pyramid", "Build Tile Pyramid", "Generate XYZ overview tiles"),
        ("mask_by_vector", "Mask by Vector", "Apply vector mask to raster"),
        ("align_rasters", "Align Rasters", "Snap grids for co-registration"),
        ("change_bitdepth", "Change Bit Depth", "Scale pixel data type"),
    ]
    for tid, name, desc in raster:
        tools.append(_tool(tid, name, "Raster", desc, ["raster", "aoi?"]))

    # --- Spectral Indices (20) ---
    indices = [
        ("ndvi", "NDVI", "Normalized Difference Vegetation Index"),
        ("ndwi", "NDWI", "Normalized Difference Water Index"),
        ("ndbi", "NDBI", "Normalized Difference Built-up Index"),
        ("savi", "SAVI", "Soil Adjusted Vegetation Index"),
        ("bsi", "BSI", "Bare Soil Index"),
        ("evi", "EVI", "Enhanced Vegetation Index"),
        ("gndvi", "GNDVI", "Green NDVI"),
        ("ndmi", "NDMI", "Normalized Difference Moisture Index"),
        ("mndwi", "MNDWI", "Modified NDWI"),
        ("ndsi", "NDSI", "Normalized Difference Snow Index"),
        ("nbr", "NBR", "Normalized Burn Ratio"),
        ("nbr2", "NBR2", "Normalized Burn Ratio 2"),
        ("ari", "ARI", "Anthocyanin Reflectance Index"),
        ("cari", "CARI", "Chlorophyll Absorption Ratio Index"),
        ("msavi", "MSAVI", "Modified SAVI"),
        ("osavi", "OSAVI", "Optimized SAVI"),
        ("tsi", "TSI", "Tasseled Cap Soil Index"),
        ("tci", "TCI", "Temperature Condition Index"),
        ("vci", "VCI", "Vegetation Condition Index"),
        ("lst_approx", "LST Approx", "Land surface temperature approximation"),
    ]
    for tid, name, desc in indices:
        tools.append(_tool(f"index_{tid}", name, "Spectral Indices", desc, ["raster"]))

    # --- Terrain / DEM-DTM-DSM (22) ---
    terrain = [
        ("dem_hillshade", "Hillshade", "Shaded relief from DEM"),
        ("dem_slope", "Slope", "Terrain slope degrees/percent"),
        ("dem_aspect", "Aspect", "Slope direction"),
        ("dem_contours", "Contours", "Elevation contour lines"),
        ("dem_tri", "TRI", "Terrain Ruggedness Index"),
        ("dem_tpi", "TPI", "Topographic Position Index"),
        ("dem_roughness", "Roughness", "Surface roughness"),
        ("dem_curvature", "Curvature", "Profile/plan curvature"),
        ("dem_viewshed", "Viewshed", "Visibility from observer point"),
        ("dem_watershed", "Watershed", "Delineate drainage basins"),
        ("dem_flow_direction", "Flow Direction", "Hydrologic flow direction"),
        ("dem_flow_accumulation", "Flow Accumulation", "Upstream accumulation"),
        ("dem_fill_sinks", "Fill Sinks", "Hydrologic DEM conditioning"),
        ("dtm_extract", "Extract DTM", "Bare-earth surface from DSM"),
        ("dsm_subtract_dtm", "Canopy Height Model", "DSM − DTM height model"),
        ("dem_resample", "Resample DEM", "Change DEM resolution"),
        ("dem_color_relief", "Color Relief", "Hypsometric tinting"),
        ("dem_profile", "Elevation Profile", "Height along a path"),
        ("dem_volume", "Cut/Fill Volume", "Volume between surfaces"),
        ("dem_to_points", "DEM to Points", "Sample elevation points"),
        ("dem_merge", "Merge DEMs", "Mosaic elevation models"),
        ("dem_difference", "DEM Difference", "Change between two DEMs"),
    ]
    for tid, name, desc in terrain:
        tools.append(_tool(tid, name, "Terrain", desc, ["dem", "aoi?"]))

    # --- Vector (24) ---
    vector = [
        ("buffer", "Buffer", "Create buffer around features"),
        ("intersect", "Intersect", "Geometric intersection"),
        ("union", "Union", "Geometric union"),
        ("difference", "Difference", "Erase by overlay"),
        ("clip_vector", "Clip Vector", "Clip features by polygon"),
        ("dissolve", "Dissolve", "Merge features by attribute"),
        ("simplify", "Simplify Geometry", "Reduce vertex count"),
        ("centroid", "Centroid", "Feature centroids"),
        ("convex_hull", "Convex Hull", "Minimum convex polygon"),
        ("voronoi", "Voronoi", "Thiessen polygons"),
        ("spatial_join", "Spatial Join", "Join attributes by location"),
        ("select_by_location", "Select by Location", "Spatial predicate query"),
        ("select_by_attribute", "Select by Attribute", "Attribute expression filter"),
        ("reproject_vector", "Reproject Vector", "Transform feature CRS"),
        ("multipart_to_single", "Multipart to Singlepart", "Explode multipart features"),
        ("points_to_line", "Points to Line", "Connect points into lines"),
        ("line_to_polygon", "Line to Polygon", "Close lines into polygons"),
        ("polygon_to_line", "Polygon to Line", "Extract boundaries"),
        ("densify", "Densify", "Add vertices along edges"),
        ("smooth_line", "Smooth Line", "Chaikin / spline smoothing"),
        ("nearest_neighbor", "Nearest Neighbor", "Distance to nearest feature"),
        ("create_grid", "Create Grid", "Fishnet / hex grid"),
        ("merge_vectors", "Merge Vectors", "Append feature collections"),
        ("validate_geometry", "Validate Geometry", "Check topology errors"),
    ]
    for tid, name, desc in vector:
        tools.append(_tool(tid, name, "Vector", desc, ["vector"]))

    # --- Classification / ML (12) ---
    ml = [
        ("unsupervised_kmeans", "K-Means Clustering", "Unsupervised land cover clusters"),
        ("supervised_rf", "Random Forest Classify", "Supervised RF classification"),
        ("supervised_svm", "SVM Classify", "Support Vector Machine"),
        ("change_detection", "Change Detection", "Pixel/object change between dates"),
        ("detect_water", "Water Detection", "Extract water bodies"),
        ("detect_flood", "Flood Detection", "Flood extent mapping"),
        ("detect_urban", "Urban Detection", "Built-up area extraction"),
        ("detect_vegetation", "Vegetation Detection", "Vegetation mask"),
        ("detect_roads", "Road Detection", "Linear road features"),
        ("detect_buildings", "Building Detection", "Building footprints"),
        ("accuracy_assessment", "Accuracy Assessment", "Confusion matrix / kappa"),
        ("segment_objects", "Object Segmentation", "Mean-shift / SLIC objects"),
    ]
    for tid, name, desc in ml:
        tools.append(_tool(tid, name, "Classification", desc, ["raster", "training?"]))

    # --- Measurement & Analysis (12) ---
    measure = [
        ("measure_distance", "Measure Distance", "Geodesic distance"),
        ("measure_area", "Measure Area", "Polygon area / perimeter"),
        ("measure_bearing", "Measure Bearing", "Azimuth between points"),
        ("time_series_stats", "Time Series Stats", "Multi-date pixel statistics"),
        ("histogram", "Histogram", "Value distribution chart"),
        ("scatter_plot_bands", "Band Scatter Plot", "Band vs band scatter"),
        ("hotspot_analysis", "Hotspot Analysis", "Getis-Ord Gi* style hotspots"),
        ("density_kernel", "Kernel Density", "Point density surface"),
        ("suitability", "Suitability Overlay", "Weighted criteria overlay"),
        ("proximity_analysis", "Proximity Analysis", "Distance surfaces"),
        ("pixel_inspector", "Pixel Inspector", "Sample values at click"),
        ("compare_dates", "Compare Dates", "Side-by-side / swipe compare"),
    ]
    for tid, name, desc in measure:
        tools.append(_tool(tid, name, "Measurement", desc, ["geometry", "raster?"]))

    # --- Conversion & Export (14) ---
    convert = [
        ("export_geotiff", "Export GeoTIFF", "Write GeoTIFF output"),
        ("export_cog", "Export COG", "Write Cloud Optimized GeoTIFF"),
        ("export_geojson", "Export GeoJSON", "Write GeoJSON vectors"),
        ("export_shapefile", "Export Shapefile", "Write ESRI Shapefile ZIP"),
        ("export_kml", "Export KML", "Write KML/KMZ"),
        ("export_csv", "Export CSV", "Attribute table to CSV"),
        ("export_png", "Export PNG Map", "Render map snapshot"),
        ("export_pdf_report", "Export PDF Report", "Analysis PDF report"),
        ("export_excel", "Export Excel", "Tabular Excel workbook"),
        ("import_geotiff", "Import GeoTIFF", "Load local satellite/DEM raster"),
        ("import_geojson", "Import GeoJSON", "Load vector GeoJSON"),
        ("import_shapefile", "Import Shapefile", "Load Shapefile ZIP"),
        ("import_csv_points", "Import CSV Points", "Points from lat/lon CSV"),
        ("wgs84_to_utm", "WGS84 ↔ UTM", "Coordinate conversion helper"),
    ]
    for tid, name, desc in convert:
        tools.append(_tool(tid, name, "Conversion", desc, ["file"]))

    # --- Visualization & Cartography (14) ---
    viz = [
        ("symbology_classify", "Classify Symbology", "Jenks / quantile color ramps"),
        ("opacity_control", "Opacity Control", "Layer transparency"),
        ("swipe_compare", "Swipe Compare", "Vertical swipe between layers"),
        ("flicker_compare", "Flicker Compare", "Toggle flicker two dates"),
        ("annotate_map", "Annotate Map", "Labels and callouts"),
        ("north_arrow_scale", "North Arrow & Scale", "Cartographic ornaments"),
        ("legend_builder", "Legend Builder", "Compose map legend"),
        ("basemap_switch", "Basemap Switch", "Offline basemap selection"),
        ("landmark_overlay", "Landmark Overlay", "Toggle landmark labels"),
        ("3d_exaggerate", "Terrain Exaggeration", "Vertical exaggeration"),
        ("fly_to_extent", "Fly to Extent", "Animate camera to layer"),
        ("bookmark_view", "Bookmark View", "Save camera position"),
        ("print_layout", "Print Layout", "Compose printable map"),
        ("timeline_animate", "Timeline Animate", "Animate multi-date stack"),
    ]
    for tid, name, desc in viz:
        tools.append(_tool(tid, name, "Visualization", desc, ["layer"]))

    assert len(tools) == 148, f"Expected 148 tools, got {len(tools)}"
    return tools


GIS_TOOLS: list[GisTool] = build_gis_tools()


def list_categories() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for t in GIS_TOOLS:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]


def get_tool(tool_id: str) -> GisTool | None:
    for t in GIS_TOOLS:
        if t["id"] == tool_id:
            return t
    return None
