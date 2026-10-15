/**
 * Demo Hello — sandboxed plugin UI (P2B).
 * Talks ONLY to the Host Shell via postMessage Host SDK.
 * Must not import Host Shell modules, read cookies, or touch Leaflet.
 */
(function () {
  "use strict";

  var boot = window.__EV_PLUGIN_BOOT__ || {};
  var parentOrigin = boot.parentOrigin || "*";
  var pending = {};
  var reqSeq = 0;

  function el(id) {
    return document.getElementById(id);
  }

  function showError(msg) {
    var node = el("err");
    if (!node) return;
    node.hidden = false;
    node.textContent = String(msg || "error");
  }

  function callHost(method, params) {
    return new Promise(function (resolve, reject) {
      var id = "r" + String(++reqSeq);
      pending[id] = { resolve: resolve, reject: reject };
      var msg = {
        v: 1,
        type: "request",
        id: id,
        plugin_id: boot.pluginId,
        version: boot.version,
        digest: boot.digest,
        method: method,
        params: params || {},
      };
      if (!window.parent || window.parent === window) {
        reject(new Error("no host parent"));
        return;
      }
      window.parent.postMessage(msg, parentOrigin === "*" ? "*" : parentOrigin);
      setTimeout(function () {
        if (pending[id]) {
          delete pending[id];
          reject(new Error("host sdk timeout: " + method));
        }
      }, 8000);
    });
  }

  window.addEventListener("message", function (ev) {
    var data = ev.data;
    if (!data || typeof data !== "object" || data.v !== 1) return;
    // Opaque/srcdoc frames: accept responses that match our boot identity.
    if (data.plugin_id && data.plugin_id !== boot.pluginId) return;
    if (data.type === "response" && data.id && pending[data.id]) {
      var p = pending[data.id];
      delete pending[data.id];
      if (data.ok === false) p.reject(new Error(data.error || "host error"));
      else p.resolve(data.result);
      return;
    }
    if (data.type === "error" && data.id && pending[data.id]) {
      var p2 = pending[data.id];
      delete pending[data.id];
      p2.reject(new Error(data.error || "host error"));
    }
  });

  function renderSynthetic(payload) {
    var body = (payload && payload.payload) || payload || {};
    el("msg").textContent = body.message || "";
    el("note").textContent = body.note || "";
    var points = body.points || [];
    var ul = el("points");
    ul.innerHTML = "";
    points.forEach(function (pt) {
      var li = document.createElement("li");
      var a = document.createElement("span");
      a.textContent = pt.label || "";
      var b = document.createElement("span");
      b.style.fontFamily = "ui-monospace, monospace";
      b.textContent = String(pt.value);
      li.appendChild(a);
      li.appendChild(b);
      ul.appendChild(li);
    });
    var h = Math.max(120, document.body.scrollHeight + 8);
    callHost("host.resize", { height: h }).catch(function () {});
  }

  function bootUi() {
    el("title").textContent = boot.name || "Demo Hello";
    el("meta").textContent =
      "slot · " +
      (boot.slot || "?") +
      " · v" +
      (boot.version || "—") +
      " · sdk " +
      (boot.hostSdkVersion || "1.0.0");
    el("badge").textContent = "sandboxed iframe · " + (boot.version || "");

    window.parent.postMessage(
      {
        v: 1,
        type: "ready",
        plugin_id: boot.pluginId,
        version: boot.version,
        digest: boot.digest,
      },
      parentOrigin === "*" ? "*" : parentOrigin
    );

    callHost("host.meta", {})
      .then(function () {
        return callHost("host.getSynthetic", {});
      })
      .then(renderSynthetic)
      .catch(function (err) {
        showError(err && err.message ? err.message : String(err));
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootUi);
  } else {
    bootUi();
  }
})();
