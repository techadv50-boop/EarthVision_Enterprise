(function () {
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var seq = 0;
  var lastAoi = null;
  var lastSyn = null;

  function el(id) { return document.getElementById(id); }

  function callHost(method, params, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var id = "otc" + (++seq);
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

  function renderBands(syn) {
    var body = (syn && syn.payload) || syn || {};
    var recipes = body.band_recipes || {};
    var keys = Object.keys(recipes);
    if (!keys.length) {
      el("bands").innerHTML = "<em>No band recipes in synthetic payload.</em>";
      return;
    }
    el("bands").innerHTML =
      "<strong>Optical true-color band recipes</strong><br/>" +
      keys
        .map(function (k) {
          var r = recipes[k] || {};
          return (
            "<div style='margin-top:4px'><code>" +
            k +
            "</code> · <code>" +
            (r.codes || "—") +
            "</code><br/><span style='color:#5d7368'>" +
            (r.formula || "") +
            "</span></div>"
          );
        })
        .join("");
  }

  function formatAoi(aoi) {
    if (!aoi) return "(none — draw an AOI in the Host Shell)";
    return (
      "<code>" +
      [aoi.west, aoi.south, aoi.east, aoi.north]
        .map(function (x) {
          return Number(x).toFixed(4);
        })
        .join(", ") +
      "</code>"
    );
  }

  function refresh() {
    clearErr();
    return callHost("host.getAoiBounds", {})
      .then(function (aoiRes) {
        lastAoi = aoiRes && aoiRes.aoi;
        el("gate").textContent =
          "AOI: " +
          (lastAoi
            ? "bound · use Host Shell true_color toolbox for map composite"
            : "none — draw an AOI, then publish a plan");
        return callHost("host.getSynthetic", {});
      })
      .then(function (syn) {
        lastSyn = syn;
        renderBands(syn);
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
    (boot.hostSdkVersion || "1.1");

  window.parent.postMessage(
    { v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest },
    parentOrigin === "*" ? "*" : parentOrigin
  );

  refresh();

  el("refresh").addEventListener("click", function () {
    refresh();
  });

  el("run").addEventListener("click", function () {
    clearErr();
    el("out").textContent = "Publishing true-color plan…";
    var body = (lastSyn && lastSyn.payload) || lastSyn || {};
    var recipes = body.band_recipes || {};
    var metrics = (body.metrics || []).slice();
    metrics.push({
      label: "AOI",
      value: lastAoi ? "bound" : "none",
    });
    var families = Object.keys(recipes);
    var summary =
      (body.message || "True color optical plan") +
      (lastAoi ? " · AOI bound" : " · no AOI") +
      (families.length ? " · " + families.length + " sensor recipes" : "");
    callHost("host.setAnalysisResult", {
      result: {
        title: "True Color (Optical)",
        summary: summary,
        metrics: metrics,
        aoi: lastAoi || null,
        band_recipes: recipes,
        optical_only: true,
        host_surface: "sdk_1.1_absorbable",
      },
    })
      .then(function () {
        el("out").textContent =
          summary +
          "\n\nBand codes published to Host analysis result.\n" +
          "Map RGB composite: use Host Shell toolbox true_color (legacy) on an optical scene.";
        return callHost("host.resize", { height: document.body.scrollHeight + 12 });
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
        el("out").textContent = "Result: —";
      });
  });
})();
