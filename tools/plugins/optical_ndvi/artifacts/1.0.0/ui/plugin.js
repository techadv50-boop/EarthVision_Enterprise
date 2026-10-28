(function () {
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var seq = 0;
  var sceneState = null;
  var lastLayerId = null;
  var RECIPES = {"NDVI": {"formula": "(NIR - RED) / (NIR + RED)", "SENTINEL-2": "B08 + B04", "LANDSAT-8": "B5 + B4", "LANDSAT-9": "B5 + B4", "LANDSAT-7": "B4 + B3", "MODIS": "B02 + B01", "cmap": "rdylgn"}};
  var MULTI = false;

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

  function currentIndex() {
    var n = el("index");
    return n ? String(n.value || "").toUpperCase() : "NDVI";
  }
  function setBusy(busy) {
    var ok = !!(sceneState && sceneState.optical_ok);
    el("render").disabled = busy || !ok;
    el("geotiff").disabled = busy || !ok || !lastLayerId;
    el("jpeg").disabled = busy || !ok;
  }
  function updateBands() {
    if (!MULTI) return;
    var bands = el("bands");
    if (!bands) return;
    var index = currentIndex();
    var block = RECIPES[index] || {};
    var family = (sceneState && sceneState.family) || "";
    var note = block[family] || "";
    bands.hidden = false;
    bands.innerHTML = "<strong>" + index + "</strong> · <code>" + (block.formula || "") + "</code>" +
      (note ? "<br/>Bands: <code>" + note + "</code>" : "");
  }
  function applyScene(scene) {
    sceneState = scene || null;
    var gate = el("gate");
    if (!scene || !scene.scene_id) {
      gate.className = "status warn";
      gate.textContent = "Inactive — select an optical scene (Sentinel-2 / Landsat 7·8·9).";
      setBusy(false);
      el("render").disabled = true;
      return;
    }
    if (!scene.optical_ok) {
      gate.className = "status warn";
      gate.textContent = "Inactive for this sensor — " + (scene.optical_block_reason || "optical only");
      setBusy(false);
      el("render").disabled = true;
      return;
    }
    gate.className = "status ok";
    gate.textContent = "Active · " + (scene.family || scene.collection || "optical") + " · " + String(scene.scene_id).slice(0, 28);
    updateBands();
    setBusy(false);
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
  if (MULTI && el("index") && el("index").tagName === "SELECT") {
    el("index").addEventListener("change", updateBands);
  }
  el("render").addEventListener("click", function () {
    clearErr();
    setBusy(true);
    var index = currentIndex();
    var cmap = (RECIPES[index] && RECIPES[index].cmap) || null;
    el("out").textContent = "Computing " + index + "…";
    callHost("host.renderIndex", { index: index, colormap: cmap }, 120000)
      .then(function (res) {
        lastLayerId = (res && res.layer_id) || null;
        el("out").textContent = (res && res.message ? res.message : index + " ready") + (res && res.formula ? "\n" + res.formula : "");
        return callHost("host.setAnalysisResult", {
          result: {
            title: index + " (Optical)",
            summary: (res && res.message) || index,
            metrics: [
              { label: "Index", value: index },
              { label: "Family", value: (sceneState && sceneState.family) || "—" },
              { label: "Formula", value: (res && res.formula) || (RECIPES[index] && RECIPES[index].formula) || "—" }
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
    var index = currentIndex();
    callHost("host.exportGeotiff", { layer_id: lastLayerId || undefined, index: index, filename: index }, 180000)
      .then(function (res) { el("out").textContent = "GeoTIFF downloaded" + (res && res.filename ? ": " + res.filename : ""); })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); })
      .then(function () { setBusy(false); });
  });
  el("jpeg").addEventListener("click", function () {
    clearErr();
    var dpiEl = document.querySelector('input[name="dpi"]:checked');
    var dpi = dpiEl && dpiEl.value === "600" ? 600 : 300;
    var index = currentIndex();
    setBusy(true);
    callHost("host.exportMapJpeg", { dpi: dpi, title: "SAT EYE " + index + " Map" }, 180000)
      .then(function (res) { el("out").textContent = "Map JPEG downloaded (" + dpi + " DPI)" + (res && res.filename ? ": " + res.filename : ""); })
      .catch(function (e) { showErr(e && e.message ? e.message : String(e)); })
      .then(function () { setBusy(false); });
  });
})();
