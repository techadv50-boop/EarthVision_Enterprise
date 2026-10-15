"""Demo GIS analysis plugin backend (worker-executed only)."""

PACK_VERSION = "1.0.0"


def render(payload=None):
    payload = payload or {}
    aoi = payload.get("aoi")
    area_hint = None
    if isinstance(aoi, dict):
        try:
            w, s, e, n = aoi["west"], aoi["south"], aoi["east"], aoi["north"]
            # Rough degree-box area proxy (demo only — not geodesic)
            area_hint = abs(float(e) - float(w)) * abs(float(n) - float(s))
        except (KeyError, TypeError, ValueError):
            area_hint = None
    return {
        "plugin_id": "demo_gis_analysis",
        "version": PACK_VERSION,
        "kind": "gis_analysis_demo",
        "message": "Controlled GIS analysis via Host SDK (no Leaflet access).",
        "aoi_degree_area_proxy": area_hint,
        "metrics": [
            {"label": "NDVI mean (demo)", "value": 0.42},
            {"label": "Cloud fraction (demo)", "value": 0.08},
        ],
        "note": "Results published through host.setAnalysisResult only.",
    }
