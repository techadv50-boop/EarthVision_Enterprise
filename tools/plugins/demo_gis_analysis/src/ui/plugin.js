(function () {
  "use strict";
  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var seq = 0;

  function el(id) { return document.getElementById(id); }
  function callHost(method, params) {
    return new Promise(function (resolve, reject) {
      var id = "g" + (++seq);
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
      }, 10000);
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

  el("meta").textContent =
    "slot · " + (boot.slot || "?") + " · v" + (boot.version || "") + " · sdk " + (boot.hostSdkVersion || "");

  window.parent.postMessage(
    { v: 1, type: "ready", plugin_id: boot.pluginId, version: boot.version, digest: boot.digest },
    parentOrigin === "*" ? "*" : parentOrigin
  );

  el("run").addEventListener("click", function () {
    el("err").hidden = true;
    callHost("host.getAoiBounds", {})
      .then(function (aoiRes) {
        var aoi = aoiRes && aoiRes.aoi;
        el("aoi").innerHTML =
          "AOI: " +
          (aoi
            ? "<code>" +
              [aoi.west, aoi.south, aoi.east, aoi.north]
                .map(function (x) { return Number(x).toFixed(4); })
                .join(", ") +
              "</code>"
            : "(none — draw an AOI in the Host Shell)");
        return callHost("host.getSynthetic", {}).then(function (syn) {
          return { aoi: aoi, syn: syn };
        });
      })
      .then(function (ctx) {
        var body = (ctx.syn && ctx.syn.payload) || ctx.syn || {};
        var metrics = body.metrics || [];
        var summary =
          (body.message || "Analysis complete") +
          (ctx.aoi ? " · AOI bound" : " · no AOI");
        el("out").textContent = summary;
        return callHost("host.setAnalysisResult", {
          result: {
            title: "Demo GIS Analysis",
            summary: summary,
            metrics: metrics,
            aoi: ctx.aoi || null,
          },
        });
      })
      .then(function () {
        return callHost("host.resize", { height: document.body.scrollHeight + 12 });
      })
      .catch(function (e) {
        showErr(e && e.message ? e.message : String(e));
      });
  });
})();
