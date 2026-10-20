(function () {
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var seq = 0;
  var sceneState = null;
  var rendered = false;

  function el(id) { return document.getElementById(id); }

  function callHost(method, params, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var id = "tc" + (++seq);
      pending[id] = { resolve: resolve, reject: reject };
      window.parent.postMessage(
        {
          v: 1,
          type: "request",
          id: id,
          plugin_id: boot.pluginId,
          version: boot.version,
          digest: boot.digest,
          method: method,
          params: params || {},
        },
        parentOrigin === "*" ? "*" : parentOrigin
      );
      setTimeout(function () {
        if (pending[id]) {
          delete pending[id];
          reject(new Error("timeout " + method));
        }
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

  function showErr(m) {
    var n = el("err");
    n.hidden = false;
    n.textContent = m;
  }

  function clearErr() {
    el("err").hidden = true;
    el("err").textContent = "";
  }

  function setBusy(busy) {
    el("render").disabled = busy || !(sceneState && sceneState.optical_ok);
    el("geotiff").disabled = busy || !(sceneState && sceneState.optical_ok);
    el("jpeg").disabled = busy || !(sceneState && sceneState.optical_ok);
  }

  function applyScene(scene) {
    sceneState = scene || null;
    var gate = el("gate");
    var bands = el("bands");
    if (!scene || !scene.scene_id) {
      gate.className = "status warn";
      gate.textContent = "Inactive — select an optical satellite image (eye icon).";
      bands.hidden = true;
      rendered = false;
      setBusy(false);
      el("render").disabled = true;
      el("geotiff").disabled = true;
      el("jpeg").disabled = true;
      return;
    }
    if (!scene.optical_ok) {
      gate.className = "status warn";
      gate.textContent =
        "Inactive for this sensor — " +
        (scene.optical_block_reason || "optical satellites only (Sentinel-2 / Landsat / MODIS).");
      bands.hidden = true;
      rendered = false;
      el("render").disabled = true;
      el("geotiff").disabled = true;
      el("jpeg").disabled = true;
      return;
    }
    gate.className = "status ok";
    gate.textContent =
      "Active · " +
      (scene.family || scene.collection || "optical") +
      " · scene " +
      String(scene.scene_id).slice(0, 28);
    var recipe = scene.band_recipe;
    if (recipe) {
      bands.hidden = false;
      bands.innerHTML =
        "<strong>True color bands</strong><br/>" +
        "RGB codes: <code>" +
        (recipe.codes || "") +
        "</code><br/>" +
        "R=<code>" +
        (recipe.R || "") +
        "</code> G=<code>" +
        (recipe.G || "") +
        "</code> B=<code>" +
        (recipe.B || "") +
        "</code><br/>" +
        "<span style='color:#5d7368'>" +
        (recipe.formula || "") +
        "</span>";
    } else {
      bands.hidden = true;
    }
    rendered = !!scene.has_true_color_overlay;
    setBusy(false);
  }

  function refreshScene() {
    return callHost("host.getSceneContext", {})
      .then(function (res) {
        applyScene(res && res.scene);
        return callHost("host.resize", { height: document.body.scrollHeight + 12 });
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
      });
  }

  el("meta").textContent =
    "slot · " +
    (boot.slot || "?") +
    " · v" +
    (boot.version || "") +
    " · sdk " +
    (boot.hostSdkVersion || "");

  window.parent.postMessage(
    { v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest },
    parentOrigin === "*" ? "*" : parentOrigin
  );

  refreshScene();
  setInterval(function () {
    refreshScene();
  }, 4000);

  el("render").addEventListener("click", function () {
    clearErr();
    setBusy(true);
    el("out").textContent = "Rendering true color composite…";
    callHost("host.renderTrueColor", {}, 120000)
      .then(function (res) {
        rendered = true;
        var recipe = (res && res.band_recipe) || (sceneState && sceneState.band_recipe);
        el("out").textContent =
          (res && res.message ? res.message : "True color ready") +
          (recipe ? "\nBands: " + recipe.codes : "");
        return callHost("host.setAnalysisResult", {
          result: {
            title: "True Color (Optical)",
            summary: (res && res.message) || "True color composite on map",
            metrics: [
              { label: "Preset", value: "true_color" },
              { label: "Bands", value: (recipe && recipe.codes) || "—" },
              { label: "Family", value: (sceneState && sceneState.family) || "—" },
            ],
          },
        });
      })
      .then(function () {
        return callHost("host.resize", { height: document.body.scrollHeight + 12 });
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
        el("out").textContent = "Result: —";
      })
      .then(function () {
        setBusy(false);
      });
  });

  el("geotiff").addEventListener("click", function () {
    clearErr();
    setBusy(true);
    el("out").textContent = "Exporting GeoTIFF…";
    callHost("host.exportGeotiff", {}, 180000)
      .then(function (res) {
        el("out").textContent =
          "GeoTIFF downloaded" + (res && res.filename ? ": " + res.filename : "");
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
      })
      .then(function () {
        setBusy(false);
      });
  });

  el("jpeg").addEventListener("click", function () {
    clearErr();
    var dpiEl = document.querySelector('input[name="dpi"]:checked');
    var dpi = dpiEl && dpiEl.value === "600" ? 600 : 300;
    setBusy(true);
    el("out").textContent = "Exporting map JPEG at " + dpi + " DPI…";
    callHost(
      "host.exportMapJpeg",
      { dpi: dpi, title: "SAT EYE True Color Map" },
      180000
    )
      .then(function (res) {
        el("out").textContent =
          "Map JPEG downloaded (" +
          dpi +
          " DPI)" +
          (res && res.filename ? ": " + res.filename : "") +
          "\nNorth arrow + scale bar attached.";
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
      })
      .then(function () {
        setBusy(false);
      });
  });
})();
