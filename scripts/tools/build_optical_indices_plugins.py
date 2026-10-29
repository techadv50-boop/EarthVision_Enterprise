#!/usr/bin/env python3
"""Build optical FCC + spectral-index plugin packs (Host SDK ≥1.5).

Generates source trees under tools/plugins/<id>/src and immutable artifacts.
Does not touch Host Shell presentation — plugins call host.renderComposite /
host.renderIndex only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "tools" / "plugins"

OPTICAL_SATS = ["SENTINEL-2", "LANDSAT-8", "LANDSAT-9", "LANDSAT-7", "MODIS"]

# Band recipes (mirror backend/app/services/satellite_bands.py)
FCC_RECIPES = {
    "false_color_infrared": {
        "label": "False Color Infrared (NIR-R-G)",
        "SENTINEL-2": {"codes": "B08-B04-B03", "formula": "R=NIR(B08), G=Red(B04), B=Green(B03)"},
        "LANDSAT-8": {"codes": "B5-B4-B3", "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"},
        "LANDSAT-9": {"codes": "B5-B4-B3", "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"},
        "LANDSAT-7": {"codes": "B4-B3-B2", "formula": "R=NIR(B4), G=Red(B3), B=Green(B2)"},
        "MODIS": {"codes": "B02-B01-B04", "formula": "R=NIR(B02), G=Red(B01), B=Green(B04)"},
    },
    "false_color_agriculture": {
        "label": "Agriculture (SWIR1-NIR-Blue)",
        "SENTINEL-2": {"codes": "B11-B08-B02", "formula": "R=SWIR1(B11), G=NIR(B08), B=Blue(B02)"},
        "LANDSAT-8": {"codes": "B6-B5-B2", "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"},
        "LANDSAT-9": {"codes": "B6-B5-B2", "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"},
        "LANDSAT-7": {"codes": "B5-B4-B1", "formula": "R=SWIR1(B5), G=NIR(B4), B=Blue(B1)"},
        "MODIS": {"codes": "B06-B02-B03", "formula": "R=SWIR1(B06), G=NIR(B02), B=Blue(B03)"},
    },
    "false_color_urban": {
        "label": "Urban / Buildup (SWIR2-SWIR1-Red)",
        "SENTINEL-2": {"codes": "B12-B11-B04", "formula": "R=SWIR2(B12), G=SWIR1(B11), B=Red(B04)"},
        "LANDSAT-8": {"codes": "B7-B6-B4", "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"},
        "LANDSAT-9": {"codes": "B7-B6-B4", "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"},
        "LANDSAT-7": {"codes": "B7-B5-B3", "formula": "R=SWIR2(B7), G=SWIR1(B5), B=Red(B3)"},
        "MODIS": {"codes": "B07-B06-B01", "formula": "R=SWIR2(B07), G=SWIR1(B06), B=Red(B01)"},
    },
    "swir_composite": {
        "label": "Shortwave Infrared (SWIR2-NIR-Red)",
        "SENTINEL-2": {"codes": "B12-B08-B04", "formula": "R=SWIR2(B12), G=NIR(B08), B=Red(B04)"},
        "LANDSAT-8": {"codes": "B7-B5-B4", "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"},
        "LANDSAT-9": {"codes": "B7-B5-B4", "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"},
        "LANDSAT-7": {"codes": "B7-B4-B3", "formula": "R=SWIR2(B7), G=NIR(B4), B=Red(B3)"},
        "MODIS": {"codes": "B07-B02-B01", "formula": "R=SWIR2(B07), G=NIR(B02), B=Red(B01)"},
    },
}

INDEX_BANDS = {
    "NDVI": {
        "formula": "(NIR - RED) / (NIR + RED)",
        "SENTINEL-2": "B08 + B04",
        "LANDSAT-8": "B5 + B4",
        "LANDSAT-9": "B5 + B4",
        "LANDSAT-7": "B4 + B3",
        "MODIS": "B02 + B01",
        "cmap": "rdylgn",
    },
    "NDWI": {
        "formula": "(GREEN - NIR) / (GREEN + NIR)",
        "SENTINEL-2": "B03 + B08",
        "LANDSAT-8": "B3 + B5",
        "LANDSAT-9": "B3 + B5",
        "LANDSAT-7": "B2 + B4",
        "MODIS": "B04 + B02",
        "cmap": "blues",
    },
    "NDBI": {
        "formula": "(SWIR - NIR) / (SWIR + NIR)",
        "SENTINEL-2": "B11 + B08",
        "LANDSAT-8": "B6 + B5",
        "LANDSAT-9": "B6 + B5",
        "LANDSAT-7": "B5 + B4",
        "MODIS": "B06 + B02",
        "cmap": "ylorbr",
    },
    "SAVI": {
        "formula": "((NIR - RED) * (1 + L)) / (NIR + RED + L)",
        "SENTINEL-2": "B08 + B04",
        "LANDSAT-8": "B5 + B4",
        "LANDSAT-9": "B5 + B4",
        "LANDSAT-7": "B4 + B3",
        "MODIS": "B02 + B01",
        "cmap": "rdylgn",
    },
    "EVI": {
        "formula": "2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)",
        "SENTINEL-2": "B08 + B04 + B02",
        "LANDSAT-8": "B5 + B4 + B2",
        "LANDSAT-9": "B5 + B4 + B2",
        "LANDSAT-7": "B4 + B3 + B1",
        "MODIS": "B02 + B01 + B03",
        "cmap": "rdylgn",
    },
    "NDMI": {
        "formula": "(NIR - SWIR) / (NIR + SWIR)",
        "SENTINEL-2": "B08 + B11",
        "LANDSAT-8": "B5 + B6",
        "LANDSAT-9": "B5 + B6",
        "LANDSAT-7": "B4 + B5",
        "MODIS": "B02 + B06",
        "cmap": "brbg",
    },
    "NBR": {
        "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
        "SENTINEL-2": "B08 + B12",
        "LANDSAT-8": "B5 + B7",
        "LANDSAT-9": "B5 + B7",
        "LANDSAT-7": "B4 + B7",
        "MODIS": "B02 + B07",
        "cmap": "rdylgn",
    },
    "BSI": {
        "formula": "((SWIR + RED) - (NIR + GREEN)) / ((SWIR + RED) + (NIR + GREEN))",
        "SENTINEL-2": "B11 + B04 + B08 + B03",
        "LANDSAT-8": "B6 + B4 + B5 + B3",
        "LANDSAT-9": "B6 + B4 + B5 + B3",
        "LANDSAT-7": "B5 + B3 + B4 + B2",
        "MODIS": "B06 + B01 + B02 + B04",
        "cmap": "soil",
    },
}

HASHED_RELS = (
    "backend/plugin.py",
    "ui/tool-meta.json",
    "ui/synthetic.json",
    "ui/panel.html",
    "ui/plugin.js",
)

CSS = """
    body { margin: 0; font: 12px/1.45 "IBM Plex Sans", system-ui, sans-serif; color: #0f2a22; background: #f4f7f5; }
    .wrap { padding: 10px 12px; }
    h1 { margin: 0; font-size: 14px; font-weight: 700; letter-spacing: 0.02em; }
    .meta { color: #5d7368; font-size: 10px; margin-top: 2px; }
    .status { margin-top: 8px; padding: 8px; border-radius: 4px; border: 1px solid #c5d4cb; background: #fff; font-size: 11px; }
    .status.warn { border-color: #e8c07a; background: #fffbeb; color: #92400e; }
    .status.ok { border-color: #86b89a; background: #ecf8f1; }
    .bands { margin-top: 8px; font-size: 11px; }
    .bands code { font: 10px/1.4 "IBM Plex Mono", monospace; background: #e8efeA; padding: 1px 4px; border-radius: 2px; }
    .row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    select { width: 100%; margin-top: 8px; padding: 6px; border: 1px solid #c5d4cb; border-radius: 4px; font-size: 12px; background: #fff; }
    button { border: 1px solid #1f6f54; background: #1f6f54; color: #fff; border-radius: 4px; padding: 6px 10px; font-size: 12px; cursor: pointer; }
    button.secondary { background: #fff; color: #0f2a22; border-color: #c5d4cb; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .dpi { display: flex; gap: 6px; align-items: center; margin-top: 6px; font-size: 11px; }
    .dpi label { display: flex; align-items: center; gap: 4px; cursor: pointer; }
    .err { color: #b91c1c; margin-top: 8px; font-size: 11px; }
    .out { margin-top: 8px; padding: 8px; border: 1px solid #e2e8f0; border-radius: 4px; background: #fff; font-size: 11px; white-space: pre-wrap; }
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def common_host_js_helpers() -> str:
    return r"""
  function el(id) { return document.getElementById(id); }
  function callHost(method, params, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var id = "op" + (++seq);
      pending[id] = { resolve: resolve, reject: reject };
      window.parent.postMessage(
        { v: 1, type: "request", id: id, plugin_id: boot.pluginId, version: boot.version, digest: boot.digest, method: method, params: params || {} },
        parentOrigin === "*" ? "*" : parentOrigin
      );
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error("timeout " + method)); }
      }, timeoutMs || 15000);
    });
  }
  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (!d || d.v !== 1 || !d.id || !pending[d.id]) return;
    var p = pending[d.id];
    delete pending[d.id];
    if (d.ok === false || d.type === "error") p.reject(new Error(d.error || "error"));
    else p.resolve(d.result);
  });
  function showErr(m) { var n = el("err"); n.hidden = false; n.textContent = m; }
  function clearErr() { el("err").hidden = true; el("err").textContent = ""; }
"""


def build_composite_plugin() -> dict:
    plugin_id = "optical_false_color"
    title = "False Color Composites (Optical)"
    description = (
        "Optical false-color RGB composites for Sentinel-2 and Landsat 7/8/9 "
        "(NIR-R-G, agriculture, urban, SWIR). Host presents via processed_preview."
    )
    presets = list(FCC_RECIPES.keys())
    default = "false_color_infrared"

    backend = f'''"""Optical false-color composite plugin (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderComposite (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

COMPOSITE_PRESETS = {json.dumps({k: {"label": v["label"], **{s: v[s] for s in OPTICAL_SATS}} for k, v in FCC_RECIPES.items()}, indent=2)}


def render(payload=None):
    payload = payload or {{}}
    preset = str(payload.get("preset") or "{default}")
    family = str(payload.get("family") or "").upper() or None
    block = COMPOSITE_PRESETS.get(preset) or COMPOSITE_PRESETS["{default}"]
    recipe = block.get(family) if family else None
    return {{
        "plugin_id": "{plugin_id}",
        "version": PACK_VERSION,
        "kind": "optical_false_color",
        "message": "False-color optical composites for Landsat 7/8/9 and Sentinel-2.",
        "optical_only": True,
        "default_preset": "{default}",
        "presets": COMPOSITE_PRESETS,
        "active_recipe": recipe,
        "export": {{"geotiff": True, "map_jpeg_dpi": [300, 600]}},
        "note": "Call host.renderComposite({{preset}}). Map presentation is Host-owned (processed_preview).",
    }}
'''

    options = "\n".join(
        f'      <option value="{k}"{" selected" if k == default else ""}>{FCC_RECIPES[k]["label"]}</option>'
        for k in presets
    )
    panel = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>{title}</h1>
    <div class="meta" id="meta">sandboxed · Host SDK 1.5</div>
    <div class="status warn" id="gate">Checking scene…</div>
    <select id="preset" aria-label="Composite preset">
{options}
    </select>
    <div class="bands" id="bands" hidden></div>
    <div class="row">
      <button type="button" id="render" disabled>Apply composite</button>
      <button type="button" id="geotiff" class="secondary" disabled>Export GeoTIFF</button>
    </div>
    <div class="dpi">
      <span>Map JPEG:</span>
      <label><input type="radio" name="dpi" value="300" checked /> 300 DPI</label>
      <label><input type="radio" name="dpi" value="600" /> 600 DPI</label>
      <button type="button" id="jpeg" class="secondary" disabled>Export map JPG</button>
    </div>
    <div class="out" id="out">Result: —</div>
    <div class="err" id="err" hidden></div>
  </div>
  <script src="./plugin.js"></script>
</body>
</html>
"""

    recipes_js = json.dumps(
        {k: {s: v[s] for s in OPTICAL_SATS} for k, v in FCC_RECIPES.items()}
    )
    plugin_js = f"""(function () {{
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {{}};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {{}};
  var seq = 0;
  var sceneState = null;
  var lastLayerId = null;
  var RECIPES = {recipes_js};
{common_host_js_helpers()}
  function setBusy(busy) {{
    var ok = !!(sceneState && sceneState.optical_ok);
    el("render").disabled = busy || !ok;
    el("geotiff").disabled = busy || !ok || !lastLayerId;
    el("jpeg").disabled = busy || !ok;
  }}
  function applyScene(scene) {{
    sceneState = scene || null;
    var gate = el("gate");
    if (!scene || !scene.scene_id) {{
      gate.className = "status warn";
      gate.textContent = "Inactive — select an optical scene (Sentinel-2 / Landsat 7·8·9).";
      el("bands").hidden = true;
      setBusy(false);
      el("render").disabled = true;
      return;
    }}
    if (!scene.optical_ok) {{
      gate.className = "status warn";
      gate.textContent = "Inactive for this sensor — " + (scene.optical_block_reason || "optical only");
      el("bands").hidden = true;
      setBusy(false);
      el("render").disabled = true;
      return;
    }}
    gate.className = "status ok";
    gate.textContent = "Active · " + (scene.family || scene.collection || "optical") + " · " + String(scene.scene_id).slice(0, 28);
    updateBands();
    setBusy(false);
  }}
  function updateBands() {{
    var preset = el("preset").value;
    var family = (sceneState && sceneState.family) || "";
    var block = RECIPES[preset] || {{}};
    var recipe = block[family];
    var bands = el("bands");
    if (!recipe) {{ bands.hidden = true; return; }}
    bands.hidden = false;
    bands.innerHTML = "<strong>Bands</strong><br/>RGB: <code>" + (recipe.codes || "") + "</code><br/><span style='color:#5d7368'>" + (recipe.formula || "") + "</span>";
  }}
  function refreshScene() {{
    return callHost("host.getSceneContext", {{}})
      .then(function (res) {{
        applyScene(res && res.scene);
        return callHost("host.resize", {{ height: document.body.scrollHeight + 12 }});
      }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }});
  }}
  el("meta").textContent = "slot · " + (boot.slot || "?") + " · v" + (boot.version || "") + " · sdk " + (boot.hostSdkVersion || "");
  window.parent.postMessage({{ v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest }}, parentOrigin === "*" ? "*" : parentOrigin);
  refreshScene();
  setInterval(refreshScene, 4000);
  el("preset").addEventListener("change", updateBands);
  el("render").addEventListener("click", function () {{
    clearErr();
    setBusy(true);
    var preset = el("preset").value;
    el("out").textContent = "Rendering " + preset + "…";
    callHost("host.renderComposite", {{ preset: preset }}, 120000)
      .then(function (res) {{
        lastLayerId = (res && res.layer_id) || ("composite-" + preset);
        el("out").textContent = (res && res.message ? res.message : "Composite ready") + (res && res.formula ? "\\n" + res.formula : "");
        return callHost("host.setAnalysisResult", {{
          result: {{
            title: "False Color (Optical)",
            summary: (res && res.message) || preset,
            metrics: [
              {{ label: "Preset", value: preset }},
              {{ label: "Family", value: (sceneState && sceneState.family) || "—" }},
              {{ label: "Formula", value: (res && res.formula) || "—" }}
            ]
          }}
        }});
      }})
      .then(function () {{ return callHost("host.resize", {{ height: document.body.scrollHeight + 12 }}); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); el("out").textContent = "Result: —"; }})
      .then(function () {{ setBusy(false); }});
  }});
  el("geotiff").addEventListener("click", function () {{
    clearErr();
    setBusy(true);
    var preset = el("preset").value;
    callHost("host.exportGeotiff", {{ layer_id: lastLayerId || ("composite-" + preset), preset: preset, filename: "False_Color_" + preset }}, 180000)
      .then(function (res) {{ el("out").textContent = "GeoTIFF downloaded" + (res && res.filename ? ": " + res.filename : ""); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }})
      .then(function () {{ setBusy(false); }});
  }});
  el("jpeg").addEventListener("click", function () {{
    clearErr();
    var dpiEl = document.querySelector('input[name="dpi"]:checked');
    var dpi = dpiEl && dpiEl.value === "600" ? 600 : 300;
    setBusy(true);
    callHost("host.exportMapJpeg", {{ dpi: dpi, title: "SAT EYE False Color Map" }}, 180000)
      .then(function (res) {{ el("out").textContent = "Map JPEG downloaded (" + dpi + " DPI)" + (res && res.filename ? ": " + res.filename : ""); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }})
      .then(function () {{ setBusy(false); }});
  }});
}})();
"""

    meta = {
        "plugin_id": plugin_id,
        "tool_id": plugin_id,
        "label": title,
        "description": description,
        "ui_strategy": "sandboxed_iframe",
        "entry_html": "ui/panel.html",
        "frontend_slot": "right_analysis_panel",
        "map_presentation": "processed_preview",
        "requires_host_capabilities": [
            "host.math.numpy",
            "host.raster.rasterio",
            "host.raster.pillow",
            "host.analytics.composites",
            "host.map.processed_preview",
            "host.raster.geotiff_export",
        ],
        "permissions": [
            "synthetic_data",
            "ui.slot.right_analysis_panel",
            "host.sdk.read_meta",
            "host.sdk.read_capabilities",
            "host.sdk.read_scene",
            "host.sdk.render_composite",
            "host.sdk.clear_map_layer",
            "host.sdk.export_geotiff",
            "host.sdk.export_map_jpeg",
            "host.sdk.set_analysis_result",
            "host.sdk.read_analysis_result",
        ],
        "host_sdk": {
            "protocol": 1,
            "version": ">=1.5.0,<2",
            "react": "forbidden",
            "leaflet": "forbidden",
            "remote_bundle": False,
            "execution": "sandboxed_iframe_srcdoc",
        },
        "optical_only": True,
        "applicable_satellites": OPTICAL_SATS,
        "notes": "Uses host.renderComposite. Presentation: processed_preview. Landsat 7/8/9 + Sentinel-2.",
    }
    synthetic = {
        "kind": plugin_id,
        "plugin_id": plugin_id,
        "version": "1.0.0",
        "message": description,
        "optical_only": True,
        "default_preset": default,
        "presets": list(presets),
        "note": "Prefer host.renderComposite when a scene is selected.",
    }
    return materialize(plugin_id, title, description, backend, panel, plugin_js, meta, synthetic)


def build_index_plugin(
    plugin_id: str,
    title: str,
    indices: list[str],
    description: str,
) -> dict:
    default = indices[0]
    index_block = {k: INDEX_BANDS[k] for k in indices}

    backend = f'''"""{title} plugin backend (worker / synthetic metadata).

Host Shell fulfills rendering via host.renderIndex (Host SDK ≥1.5).
"""

PACK_VERSION = "1.0.0"

INDEX_RECIPES = {json.dumps(index_block, indent=2)}


def render(payload=None):
    payload = payload or {{}}
    index = str(payload.get("index") or "{default}").upper()
    family = str(payload.get("family") or "").upper() or None
    block = INDEX_RECIPES.get(index) or INDEX_RECIPES["{default}"]
    bands = block.get(family) if family else None
    return {{
        "plugin_id": "{plugin_id}",
        "version": PACK_VERSION,
        "kind": "{plugin_id}",
        "message": {json.dumps(description)},
        "optical_only": True,
        "default_index": "{default}",
        "indices": INDEX_RECIPES,
        "active_bands": bands,
        "export": {{"geotiff": True, "map_jpeg_dpi": [300, 600]}},
        "note": "Call host.renderIndex({{index}}). Map presentation is Host-owned (processed_preview).",
    }}
'''

    if len(indices) == 1:
        select_html = f'<input type="hidden" id="index" value="{default}" />'
        select_note = f'<div class="bands"><strong>Index</strong> <code>{default}</code> · {INDEX_BANDS[default]["formula"]}</div>'
    else:
        opts = "\n".join(
            f'      <option value="{k}"{" selected" if k == default else ""}>{k} — {INDEX_BANDS[k]["formula"]}</option>'
            for k in indices
        )
        select_html = f'<select id="index" aria-label="Spectral index">\n{opts}\n    </select>'
        select_note = '<div class="bands" id="bands" hidden></div>'

    panel = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>{title}</h1>
    <div class="meta" id="meta">sandboxed · Host SDK 1.5</div>
    <div class="status warn" id="gate">Checking scene…</div>
    {select_html}
    {select_note}
    <div class="row">
      <button type="button" id="render" disabled>Apply index</button>
      <button type="button" id="geotiff" class="secondary" disabled>Export GeoTIFF</button>
    </div>
    <div class="dpi">
      <span>Map JPEG:</span>
      <label><input type="radio" name="dpi" value="300" checked /> 300 DPI</label>
      <label><input type="radio" name="dpi" value="600" /> 600 DPI</label>
      <button type="button" id="jpeg" class="secondary" disabled>Export map JPG</button>
    </div>
    <div class="out" id="out">Result: —</div>
    <div class="err" id="err" hidden></div>
  </div>
  <script src="./plugin.js"></script>
</body>
</html>
"""

    recipes_js = json.dumps(index_block)
    multi = "true" if len(indices) > 1 else "false"
    plugin_js = f"""(function () {{
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {{}};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {{}};
  var seq = 0;
  var sceneState = null;
  var lastLayerId = null;
  var RECIPES = {recipes_js};
  var MULTI = {multi};
{common_host_js_helpers()}
  function currentIndex() {{
    var n = el("index");
    return n ? String(n.value || "").toUpperCase() : "{default}";
  }}
  function setBusy(busy) {{
    var ok = !!(sceneState && sceneState.optical_ok);
    el("render").disabled = busy || !ok;
    el("geotiff").disabled = busy || !ok || !lastLayerId;
    el("jpeg").disabled = busy || !ok;
  }}
  function updateBands() {{
    if (!MULTI) return;
    var bands = el("bands");
    if (!bands) return;
    var index = currentIndex();
    var block = RECIPES[index] || {{}};
    var family = (sceneState && sceneState.family) || "";
    var note = block[family] || "";
    bands.hidden = false;
    bands.innerHTML = "<strong>" + index + "</strong> · <code>" + (block.formula || "") + "</code>" +
      (note ? "<br/>Bands: <code>" + note + "</code>" : "");
  }}
  function applyScene(scene) {{
    sceneState = scene || null;
    var gate = el("gate");
    if (!scene || !scene.scene_id) {{
      gate.className = "status warn";
      gate.textContent = "Inactive — select an optical scene (Sentinel-2 / Landsat 7·8·9).";
      setBusy(false);
      el("render").disabled = true;
      return;
    }}
    if (!scene.optical_ok) {{
      gate.className = "status warn";
      gate.textContent = "Inactive for this sensor — " + (scene.optical_block_reason || "optical only");
      setBusy(false);
      el("render").disabled = true;
      return;
    }}
    gate.className = "status ok";
    gate.textContent = "Active · " + (scene.family || scene.collection || "optical") + " · " + String(scene.scene_id).slice(0, 28);
    updateBands();
    setBusy(false);
  }}
  function refreshScene() {{
    return callHost("host.getSceneContext", {{}})
      .then(function (res) {{
        applyScene(res && res.scene);
        return callHost("host.resize", {{ height: document.body.scrollHeight + 12 }});
      }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }});
  }}
  el("meta").textContent = "slot · " + (boot.slot || "?") + " · v" + (boot.version || "") + " · sdk " + (boot.hostSdkVersion || "");
  window.parent.postMessage({{ v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest }}, parentOrigin === "*" ? "*" : parentOrigin);
  refreshScene();
  setInterval(refreshScene, 4000);
  if (MULTI && el("index") && el("index").tagName === "SELECT") {{
    el("index").addEventListener("change", updateBands);
  }}
  el("render").addEventListener("click", function () {{
    clearErr();
    setBusy(true);
    var index = currentIndex();
    var cmap = (RECIPES[index] && RECIPES[index].cmap) || null;
    el("out").textContent = "Computing " + index + "…";
    callHost("host.renderIndex", {{ index: index, colormap: cmap }}, 120000)
      .then(function (res) {{
        lastLayerId = (res && res.layer_id) || null;
        el("out").textContent = (res && res.message ? res.message : index + " ready") + (res && res.formula ? "\\n" + res.formula : "");
        return callHost("host.setAnalysisResult", {{
          result: {{
            title: index + " (Optical)",
            summary: (res && res.message) || index,
            metrics: [
              {{ label: "Index", value: index }},
              {{ label: "Family", value: (sceneState && sceneState.family) || "—" }},
              {{ label: "Formula", value: (res && res.formula) || (RECIPES[index] && RECIPES[index].formula) || "—" }}
            ]
          }}
        }});
      }})
      .then(function () {{ return callHost("host.resize", {{ height: document.body.scrollHeight + 12 }}); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); el("out").textContent = "Result: —"; }})
      .then(function () {{ setBusy(false); }});
  }});
  el("geotiff").addEventListener("click", function () {{
    clearErr();
    setBusy(true);
    var index = currentIndex();
    callHost("host.exportGeotiff", {{ layer_id: lastLayerId || undefined, index: index, filename: index }}, 180000)
      .then(function (res) {{ el("out").textContent = "GeoTIFF downloaded" + (res && res.filename ? ": " + res.filename : ""); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }})
      .then(function () {{ setBusy(false); }});
  }});
  el("jpeg").addEventListener("click", function () {{
    clearErr();
    var dpiEl = document.querySelector('input[name="dpi"]:checked');
    var dpi = dpiEl && dpiEl.value === "600" ? 600 : 300;
    var index = currentIndex();
    setBusy(true);
    callHost("host.exportMapJpeg", {{ dpi: dpi, title: "SAT EYE " + index + " Map" }}, 180000)
      .then(function (res) {{ el("out").textContent = "Map JPEG downloaded (" + dpi + " DPI)" + (res && res.filename ? ": " + res.filename : ""); }})
      .catch(function (e) {{ showErr(e && e.message ? e.message : String(e)); }})
      .then(function () {{ setBusy(false); }});
  }});
}})();
"""

    meta = {
        "plugin_id": plugin_id,
        "tool_id": plugin_id,
        "label": title,
        "description": description,
        "ui_strategy": "sandboxed_iframe",
        "entry_html": "ui/panel.html",
        "frontend_slot": "right_analysis_panel",
        "map_presentation": "processed_preview",
        "requires_host_capabilities": [
            "host.math.numpy",
            "host.raster.rasterio",
            "host.raster.pillow",
            "host.analytics.indices",
            "host.map.processed_preview",
            "host.raster.geotiff_export",
        ],
        "permissions": [
            "synthetic_data",
            "ui.slot.right_analysis_panel",
            "host.sdk.read_meta",
            "host.sdk.read_capabilities",
            "host.sdk.read_scene",
            "host.sdk.render_index",
            "host.sdk.clear_map_layer",
            "host.sdk.export_geotiff",
            "host.sdk.export_map_jpeg",
            "host.sdk.set_analysis_result",
            "host.sdk.read_analysis_result",
        ],
        "host_sdk": {
            "protocol": 1,
            "version": ">=1.5.0,<2",
            "react": "forbidden",
            "leaflet": "forbidden",
            "remote_bundle": False,
            "execution": "sandboxed_iframe_srcdoc",
        },
        "optical_only": True,
        "applicable_satellites": OPTICAL_SATS,
        "notes": f"Uses host.renderIndex. Indices: {', '.join(indices)}. Landsat 7/8/9 + Sentinel-2.",
    }
    synthetic = {
        "kind": plugin_id,
        "plugin_id": plugin_id,
        "version": "1.0.0",
        "message": description,
        "optical_only": True,
        "default_index": default,
        "indices": indices,
        "note": "Prefer host.renderIndex when a scene is selected.",
    }
    return materialize(plugin_id, title, description, backend, panel, plugin_js, meta, synthetic)


def materialize(
    plugin_id: str,
    title: str,
    description: str,
    backend: str,
    panel: str,
    plugin_js: str,
    meta: dict,
    synthetic: dict,
    version: str = "1.0.0",
) -> dict:
    src = PLUGINS / plugin_id / "src"
    if src.exists():
        shutil.rmtree(src)
    write(src / "backend" / "plugin.py", backend)
    write(src / "ui" / "panel.html", panel)
    write(src / "ui" / "plugin.js", plugin_js)
    write(src / "ui" / "tool-meta.json", json.dumps(meta, indent=2))
    write(src / "ui" / "synthetic.json", json.dumps(synthetic, indent=2))

    dest = PLUGINS / plugin_id / "artifacts" / version
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in HASHED_RELS:
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, out)

    # Pin version string in backend
    plugin_py = dest / "backend" / "plugin.py"
    plugin_py.write_text(
        plugin_py.read_text(encoding="utf-8").replace(
            'PACK_VERSION = "1.0.0"', f'PACK_VERSION = "{version}"'
        ),
        encoding="utf-8",
    )
    syn = json.loads((dest / "ui" / "synthetic.json").read_text(encoding="utf-8"))
    syn["version"] = version
    write(dest / "ui" / "synthetic.json", json.dumps(syn, indent=2))

    lines = [f"{sha256_file(dest / rel)}  {rel}" for rel in HASHED_RELS]
    sums = dest / "SHA256SUMS"
    write(sums, "\n".join(lines))
    pack_digest = "sha256:" + sha256_file(sums)
    pack_meta = {
        "plugin_id": plugin_id,
        "tool_id": plugin_id,
        "name": title,
        "description": description,
        "version": version,
        "digest": pack_digest,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_sdk": ">=1.5.0,<2",
        "compatible_host_api": ">=1.5.0,<2",
        "ui_strategy": "sandboxed_iframe",
        "frontend_slot": "right_analysis_panel",
        "permissions": meta["permissions"],
        "entry": {
            "backend": "backend/plugin.py",
            "ui_meta": "ui/tool-meta.json",
            "ui_entry": "ui/panel.html",
        },
        "execution_model": "static_synthetic_only",
        "optical_only": True,
        "applicable_satellites": OPTICAL_SATS,
        "map_presentation": "processed_preview",
    }
    write(dest / "pack.json", json.dumps(pack_meta, indent=2))

    # Zip for Admin upload. Do not use Path.with_suffix on x.y.z — it strips to x.y.zip.
    releases = PLUGINS / plugin_id / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    zip_base = str(releases / f"{plugin_id}-{version}")
    zip_path = Path(zip_base + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(zip_base, "zip", root_dir=dest)

    install = PLUGINS / plugin_id / "INSTALL.md"
    write(
        install,
        f"""# {title}

**Plugin id:** `{plugin_id}`  
**Version:** `{version}`  
**Host SDK:** `>=1.5.0,<2`  
**Map presentation:** `processed_preview`  
**Satellites:** Sentinel-2, Landsat-7, Landsat-8, Landsat-9 (MODIS when available)  
**Publisher:** `sateye-optical-indices` (Ed25519 `SIGNATURE.json` required in production)

## Install (Admin only)

1. Deploy Host Shell with SDK **1.5+** (includes `host.renderComposite` / `host.renderIndex`).
2. Production trust: merge `tools/publishers/approved_publishers.optical_indices.json`  
   into the live `EV_PACK_PUBLISHERS` file (volume  
   `/data/tool_packs/publishers/approved_publishers.json`).
3. Admin → Plugins → Upload Plugin → choose the **signed** zip  
   `tools/plugins/{plugin_id}/releases/{plugin_id}-{version}.zip`
4. Place under Tool Tree → Activate.

## Behaviour

- Active only when an **optical** scene eye is ON.
- Plugin never touches Leaflet; Host presents soft preview + swipe.
- Export GeoTIFF / map JPEG via Host SDK.

Digest: `{pack_digest}`
""",
    )
    return {"plugin_id": plugin_id, "version": version, "digest": pack_digest}


def main() -> int:
    results = [
        build_composite_plugin(),
        build_index_plugin(
            "optical_ndvi",
            "NDVI (Optical)",
            ["NDVI"],
            "Normalized Difference Vegetation Index for Sentinel-2 and Landsat 7/8/9.",
        ),
        build_index_plugin(
            "optical_ndwi",
            "NDWI (Optical)",
            ["NDWI"],
            "McFeeters NDWI water index for Sentinel-2 and Landsat 7/8/9.",
        ),
        build_index_plugin(
            "optical_ndbi",
            "NDBI (Optical)",
            ["NDBI"],
            "Normalized Difference Built-up Index for Sentinel-2 and Landsat 7/8/9.",
        ),
        build_index_plugin(
            "optical_spectral_indices",
            "Spectral Indices (Optical)",
            ["SAVI", "EVI", "NDMI", "NBR", "BSI"],
            "Additional optical indices (SAVI, EVI, NDMI, NBR, BSI) for Landsat 7/8/9 and Sentinel-2.",
        ),
    ]
    print(json.dumps({"built": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
