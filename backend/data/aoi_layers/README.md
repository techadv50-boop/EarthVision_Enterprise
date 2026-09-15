# SatPass AOI shapefile repository

Admin users upload district or city shapefiles as **zip** files (`.shp` + `.shx` + `.dbf`, optional `.prj`).

Each uploaded layer is stored here as:

```
<layer-id>/source.zip
<layer-id>/features.geojson
<layer-id>/index.json
```

Operators use these layers in Predict: click one or more districts/cities to set the AOI. Pass reports and maps use those polygons only (no extra point buffer).

Only admins can add or remove layers. All signed-in users can view a layer and select features.
