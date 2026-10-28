(function () {
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var seq = 0;
  var sceneState = null;
  var lastLayerId = null;
  var RECIPES = {"false_color_infrared": {"SENTINEL-2": {"codes": "B08-B04-B03", "formula": "R=NIR(B08), G=Red(B04), B=Green(B03)"}, "LANDSAT-8": {"codes": "B5-B4-B3", "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"}, "LANDSAT-9": {"codes": "B5-B4-B3", "formula": "R=NIR(B5), G=Red(B4), B=Green(B3)"}, "LANDSAT-7": {"codes": "B4-B3-B2", "formula": "R=NIR(B4), G=Red(B3), B=Green(B2)"}, "MODIS": {"codes": "B02-B01-B04", "formula": "R=NIR(B02), G=Red(B01), B=Green(B04)"}}, "false_color_agriculture": {"SENTINEL-2": {"codes": "B11-B08-B02", "formula": "R=SWIR1(B11), G=NIR(B08), B=Blue(B02)"}, "LANDSAT-8": {"codes": "B6-B5-B2", "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"}, "LANDSAT-9": {"codes": "B6-B5-B2", "formula": "R=SWIR1(B6), G=NIR(B5), B=Blue(B2)"}, "LANDSAT-7": {"codes": "B5-B4-B1", "formula": "R=SWIR1(B5), G=NIR(B4), B=Blue(B1)"}, "MODIS": {"codes": "B06-B02-B03", "formula": "R=SWIR1(B06), G=NIR(B02), B=Blue(B03)"}}, "false_color_urban": {"SENTINEL-2": {"codes": "B12-B11-B04", "formula": "R=SWIR2(B12), G=SWIR1(B11), B=Red(B04)"}, "LANDSAT-8": {"codes": "B7-B6-B4", "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"}, "LANDSAT-9": {"codes": "B7-B6-B4", "formula": "R=SWIR2(B7), G=SWIR1(B6), B=Red(B4)"}, "LANDSAT-7": {"codes": "B7-B5-B3", "formula": "R=SWIR2(B7), G=SWIR1(B5), B=Red(B3)"}, "MODIS": {"codes": "B07-B06-B01", "formula": "R=SWIR2(B07), G=SWIR1(B06), B=Red(B01)"}}, "swir_composite": {"SENTINEL-2": {"codes": "B12-B08-B04", "formula": "R=SWIR2(B12), G=NIR(B08), B=Red(B04)"}, "LANDSAT-8": {"codes": "B7-B5-B4", "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"}, "LANDSAT-9": {"codes": "B7-B5-B4", "formula": "R=SWIR2(B7), G=NIR(B5), B=Red(B4)"}, "LANDSAT-7": {"codes": "B7-B4-B3", "formula": "R=SWIR2(B7), G=NIR(B4), B=Red(B3)"}, "MODIS": {"codes": "B07-B02-B01", "formula": "R=SWIR2(B07), G=NIR(B02), B=Red(B01)"}}};

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

  function setBusy(busy) {
    var ok = !!(sceneState && sceneState.optical_ok);
    el("render").disabled = busy || !ok;
    el("geotiff").disabled = busy || !ok || !lastLayerId;
    el("jpeg").disabled = busy || !ok;
  }
  function applyScene(scene) {
    sceneState = scene || null;
    var gate = el("gate");
    if (!scene || !scene.scene_id) {
      gate.className = "status warn";
      gate.textContent = "Inactive — select an optical scene (Sentinel-2 / Landsat 7·8·9).";
      el("bands").hidden = true;
      setBusy(false);
      el("render").disabled = true;
      return;
    }
    if (!scene.optical_ok) {
      gate.className = "status warn";
      gate.textContent = "Inactive for this sensor — " + (scene.optical_block_reason || "optical only");
      el("bands").hidden = true;
      setBusy(false);
      el("render").disabled = true;
      return;
    }
    gate.className = "status ok";
    gate.textContent = "Active · " + (scene.family || scene.collection || "optical") + " · " + String(scene.scene_id).slice(0, 28);
    updateBands();
    setBusy(false);
  }
  function updateBands() {
    var preset = el("preset").value;
    var family = (sceneState && sceneState.family) || "";
    var block = RECIPES[preset] || {};
    var recipe = block[family];
    var bands = el("bands");
    if (!recipe) { bands.hidden = true; return; }
    bands.hidden = false;
    bands.innerHTML = "<strong>Bands</strong><br/>RGB: <code>" + (recipe.codes || "") + "</code><br/><span style='color:#5d7368'>" + (recipe.formula || "") + "</span>";
  }
  function refreshScene() {
    return callHost("host.getSceneContext", {})
      .then(function (res) {
        applyScene(res && res.scene);
        return callHost("host.resize", { height: document.body.scrollHeight + 12 });
      })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); });
  }
  el("meta").textContent = "slot · " + (boot.slot || "?") + " · v" + (boot.version || "") + " · sdk " + (boot.hostSdkVersion || "");
  window.parent.postMessage({ v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest }, parentOrigin === "*" ? "*" : parentOrigin);
  refreshScene();
  setInterval(refreshScene, 4000);
  el("preset").addEventListener("change", updateBands);
  el("render").addEventListener("click", function () {
    clearErr();
    setBusy(true);
    var preset = el("preset").value;
    el("out").textContent = "Rendering " + preset + "…";
    callHost("host.renderComposite", { preset: preset }, 120000)
      .then(function (res) {
        lastLayerId = (res && res.layer_id) || ("composite-" + preset);
        el("out").textContent = (res && res.message ? res.message : "Composite ready") + (res && res.formula ? "\n" + res.formula : "");
        return callHost("host.setAnalysisResult", {
          result: {
            title: "False Color (Optical)",
            summary: (res && res.message) || preset,
            metrics: [
              { label: "Preset", value: preset },
              { label: "Family", value: (sceneState && sceneState.family) || "—" },
              { label: "Formula", value: (res && res.formula) || "—" }
            ]
          }
        });
      })
      .then(function () { return callHost("host.resize", { height: document.body.scrollHeight + 12 }); })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); el("out").textContent = "Result: —"; })
      .then(function () { setBusy(false); });
  });
  el("geotiff").addEventListener("click", function () {
    clearErr();
    setBusy(true);
    var preset = el("preset").value;
    callHost("host.exportGeotiff", { layer_id: lastLayerId || ("composite-" + preset), preset: preset, filename: "False_Color_" + preset }, 180000)
      .then(function (res) { el("out").textContent = "GeoTIFF downloaded" + (res && res.filename ? ": " + res.filename : ""); })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); })
      .then(function () { setBusy(false); });
  });
  el("jpeg").addEventListener("click", function () {
    clearErr();
    var dpiEl = document.querySelector('input[name="dpi"]:checked');
    var dpi = dpiEl && dpiEl.value === "600" ? 600 : 300;
    setBusy(true);
    callHost("host.exportMapJpeg", { dpi: dpi, title: "SAT EYE False Color Map" }, 180000)
      .then(function (res) { el("out").textContent = "Map JPEG downloaded (" + dpi + " DPI)" + (res && res.filename ? ": " + res.filename : ""); })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); })
      .then(function () { setBusy(false); });
  });
})();
