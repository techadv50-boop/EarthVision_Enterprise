import { useEffect, useRef, useState } from 'react';
import { pluginService, type PluginFrontendManifest } from '../services/pluginService';
import { usePluginHost } from './PluginHostContext';
import {
  assertIdentityMatch,
  HostSdkValidationError,
  PLUGIN_HOST_SDK_VERSION,
  validatePluginMessage,
  type HostToPluginMessage,
} from './hostSdk/v1';

export interface SandboxedPluginFrameProps {
  pluginId: string;
  version: string;
  name: string;
  digest?: string | null;
  slot: string;
  className?: string;
}

/**
 * Loads independent plugin UI inside a sandboxed iframe (srcdoc).
 *
 * - Does NOT execute uploaded JS in the privileged React Host Shell.
 * - sandbox="allow-scripts" without allow-same-origin → opaque origin.
 * - postMessage bridge validates source, identity, and method allowlist.
 */
export function SandboxedPluginFrame({
  pluginId,
  version,
  name,
  digest: digestProp,
  slot,
  className,
}: SandboxedPluginFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const host = usePluginHost();
  const hostRef = useRef(host);
  hostRef.current = host;
  const [height, setHeight] = useState(160);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [srcdoc, setSrcdoc] = useState<string | null>(null);
  const pinRef = useRef({ pluginId, version, digest: digestProp || '' });
  const permissionsRef = useRef<string[]>([]);

  useEffect(() => {
    pinRef.current = { pluginId, version, digest: digestProp || '' };
  }, [pluginId, version, digestProp]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSrcdoc(null);

    (async () => {
      try {
        const manifest: PluginFrontendManifest = await pluginService.frontendManifest(pluginId);
        if (cancelled) return;
        if (manifest.version !== version) {
          throw new Error(
            `active pin version ${manifest.version} != requested ${version} (stale UI)`,
          );
        }
        if (digestProp && manifest.digest !== digestProp) {
          throw new Error('digest mismatch vs Host Shell registry pin');
        }
        pinRef.current = {
          pluginId,
          version: manifest.version,
          digest: manifest.digest,
        };
        permissionsRef.current = Array.isArray(manifest.permissions)
          ? manifest.permissions
          : [];

        const entryRel = (manifest.entry_html || 'ui/panel.html').replace(/^ui\//, '');
        const html = await pluginService.uiAssetText(pluginId, entryRel);
        // Prefer inlining plugin.js so srcdoc does not need network (opaque origin).
        let pluginJs = '';
        try {
          pluginJs = await pluginService.uiAssetText(pluginId, 'plugin.js');
        } catch {
          pluginJs = '';
        }
        if (cancelled) return;

        const boot = {
          pluginId: manifest.plugin_id,
          version: manifest.version,
          digest: manifest.digest,
          name: manifest.name || name,
          slot: manifest.frontend_slot || slot,
          hostSdkVersion: manifest.host_sdk_version || PLUGIN_HOST_SDK_VERSION,
          parentOrigin: window.location.origin,
        };

        // Strip external script tags; inject boot + inlined plugin.js
        let bodyHtml = html.replace(
          /<script\b[^>]*\bsrc=["'][^"']*plugin\.js["'][^>]*>\s*<\/script>/gi,
          '',
        );
        const injection = `
<script>
window.__EV_PLUGIN_BOOT__ = ${JSON.stringify(boot)};
</script>
<script>
${pluginJs}
</script>`;
        if (/<\/body>/i.test(bodyHtml)) {
          bodyHtml = bodyHtml.replace(/<\/body>/i, `${injection}</body>`);
        } else {
          bodyHtml = `${bodyHtml}${injection}`;
        }

        // CSP meta inside srcdoc: no network, no parent escape
        if (!/http-equiv=["']Content-Security-Policy["']/i.test(bodyHtml)) {
          const csp =
            `<meta http-equiv="Content-Security-Policy" content="` +
            `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; ` +
            `img-src data:; font-src data:; base-uri 'none'; form-action 'none'; ` +
            `connect-src 'none'; frame-ancestors 'none'" />`;
          if (/<head[^>]*>/i.test(bodyHtml)) {
            bodyHtml = bodyHtml.replace(/<head[^>]*>/i, (m) => `${m}${csp}`);
          } else {
            bodyHtml = `<head>${csp}</head>${bodyHtml}`;
          }
        }

        setSrcdoc(bodyHtml);
        setLoading(false);
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load plugin UI');
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pluginId, version, digestProp, name, slot]);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const frame = iframeRef.current;
      // Critical: only accept messages from OUR iframe's contentWindow
      if (!frame || ev.source !== frame.contentWindow) {
        return;
      }
      try {
        const msg = validatePluginMessage(ev.data);
        assertIdentityMatch(msg, pinRef.current);

        if (msg.type === 'ready') {
          return;
        }

        const replyOk = (result: unknown): HostToPluginMessage => ({
          v: 1,
          type: 'response',
          id: msg.id,
          plugin_id: msg.plugin_id,
          version: msg.version,
          digest: msg.digest,
          ok: true,
          result,
        });

        // Local chrome + GIS Host APIs (no Leaflet / no tokens)
        if (msg.method === 'host.resize') {
          const h = msg.params.height;
          if (typeof h === 'number' && h >= 40 && h <= 4000) {
            setHeight(Math.round(h));
          }
          frame.contentWindow?.postMessage(
            replyOk({ height: typeof h === 'number' ? Math.round(h) : 160 }),
            '*',
          );
          return;
        }
        if (msg.method === 'host.getAoiBounds') {
          frame.contentWindow?.postMessage(
            replyOk({ aoi: hostRef.current.aoiBounds, source: 'host' }),
            '*',
          );
          return;
        }
        if (msg.method === 'host.setAnalysisResult') {
          const payload = msg.params.result;
          if (!payload || typeof payload !== 'object') {
            throw new HostSdkValidationError('result object required');
          }
          const r = payload as Record<string, unknown>;
          hostRef.current.setAnalysisResult({
            pluginId: msg.plugin_id,
            version: msg.version,
            title: typeof r.title === 'string' ? r.title : msg.plugin_id,
            summary: typeof r.summary === 'string' ? r.summary : undefined,
            metrics: Array.isArray(r.metrics)
              ? (r.metrics as Array<{ label: string; value: string | number }>)
              : undefined,
            updatedAt: new Date().toISOString(),
          });
          // Persist via authenticated Host bridge (also enforces permissions)
          void pluginService.hostSdk(pluginId, {
            v: 1,
            type: 'request',
            id: msg.id,
            plugin_id: msg.plugin_id,
            version: msg.version,
            digest: msg.digest,
            method: msg.method,
            params: msg.params,
          });
          frame.contentWindow?.postMessage(replyOk({ stored: true }), '*');
          return;
        }
        if (msg.method === 'host.getAnalysisResult') {
          const local = hostRef.current.getAnalysisResult(msg.plugin_id);
          frame.contentWindow?.postMessage(replyOk(local || { result: null }), '*');
          return;
        }

        const METHOD_PERMS: Record<string, string> = {
          'host.getSceneContext': 'host.sdk.read_scene',
          'host.renderTrueColor': 'host.sdk.render_true_color',
          'host.clearMapLayer': 'host.sdk.clear_map_layer',
          'host.exportGeotiff': 'host.sdk.export_geotiff',
          'host.exportMapJpeg': 'host.sdk.export_map_jpeg',
        };
        const needPerm = METHOD_PERMS[msg.method];
        if (needPerm && !permissionsRef.current.includes(needPerm)) {
          throw new HostSdkValidationError(
            `permission denied for ${msg.method}: requires ${needPerm}`,
          );
        }

        if (msg.method === 'host.getSceneContext') {
          const scene = hostRef.current.sceneContext;
          frame.contentWindow?.postMessage(
            replyOk({
              scene: scene || null,
              source: 'host',
            }),
            '*',
          );
          return;
        }

        if (msg.method === 'host.clearMapLayer') {
          void (async () => {
            try {
              const handlers = hostRef.current.getImageryHandlers();
              if (!handlers?.clearMapLayer && !handlers?.clearTrueColor) {
                throw new Error('Host map clear handler not registered');
              }
              if (handlers.clearMapLayer) {
                await handlers.clearMapLayer({
                  layer_id:
                    typeof msg.params.layer_id === 'string'
                      ? msg.params.layer_id
                      : undefined,
                  label_includes:
                    typeof msg.params.label_includes === 'string'
                      ? msg.params.label_includes
                      : undefined,
                  restore_scenes: msg.params.restore_scenes !== false,
                });
              } else {
                await handlers.clearTrueColor?.();
              }
              hostRef.current.setToolRunStatus({
                pluginId: msg.plugin_id,
                status: 'idle',
                message: 'Map layer cleared',
                updatedAt: new Date().toISOString(),
              });
              frame.contentWindow?.postMessage(replyOk({ ok: true, cleared: true }), '*');
            } catch (err: unknown) {
              const reply: HostToPluginMessage = {
                v: 1,
                type: 'error',
                id: msg.id,
                plugin_id: pluginId,
                ok: false,
                error: err instanceof Error ? err.message : 'clear map layer failed',
                code: 'imagery_error',
              };
              frame.contentWindow?.postMessage(reply, '*');
            }
          })();
          return;
        }

        if (
          msg.method === 'host.renderTrueColor' ||
          msg.method === 'host.exportGeotiff' ||
          msg.method === 'host.exportMapJpeg'
        ) {
          void (async () => {
            try {
              const handlers = hostRef.current.getImageryHandlers();
              if (!handlers) {
                throw new Error('Host imagery handlers not registered');
              }
              let result: Record<string, unknown>;
              if (msg.method === 'host.renderTrueColor') {
                hostRef.current.setToolRunStatus({
                  pluginId: msg.plugin_id,
                  status: 'processing',
                  message: 'Rendering true color…',
                  updatedAt: new Date().toISOString(),
                });
                result = await handlers.renderTrueColor();
                hostRef.current.setToolRunStatus({
                  pluginId: msg.plugin_id,
                  status: 'applied',
                  message:
                    typeof result.message === 'string'
                      ? result.message
                      : 'True color applied on map',
                  updatedAt: new Date().toISOString(),
                });
              } else if (msg.method === 'host.exportGeotiff') {
                result = await handlers.exportGeotiff();
              } else {
                const dpiRaw = msg.params.dpi;
                const dpi: 300 | 600 = dpiRaw === 600 ? 600 : 300;
                const title =
                  typeof msg.params.title === 'string' ? msg.params.title : undefined;
                result = await handlers.exportMapJpeg({ dpi, title });
              }
              frame.contentWindow?.postMessage(replyOk(result), '*');
            } catch (err: unknown) {
              if (msg.method === 'host.renderTrueColor') {
                hostRef.current.setToolRunStatus({
                  pluginId: msg.plugin_id,
                  status: 'failed',
                  message: err instanceof Error ? err.message : 'Could not apply tool',
                  updatedAt: new Date().toISOString(),
                });
              }
              const reply: HostToPluginMessage = {
                v: 1,
                type: 'error',
                id: msg.id,
                plugin_id: pluginId,
                ok: false,
                error: err instanceof Error ? err.message : 'imagery action failed',
                code: 'imagery_error',
              };
              frame.contentWindow?.postMessage(reply, '*');
            }
          })();
          return;
        }

        void (async () => {
          try {
            const params =
              msg.method === 'host.getAoiBounds'
                ? { ...msg.params, aoi: hostRef.current.aoiBounds }
                : msg.params;
            const res = await pluginService.hostSdk(pluginId, {
              v: 1,
              type: 'request',
              id: msg.id,
              plugin_id: msg.plugin_id,
              version: msg.version,
              digest: msg.digest,
              method: msg.method,
              params,
            });
            const reply: HostToPluginMessage =
              res && res.ok === false
                ? {
                    v: 1,
                    type: 'error',
                    id: msg.id,
                    plugin_id: pluginId,
                    ok: false,
                    error: String(res.error || 'host sdk rejected'),
                    code: String(res.code || 'host_sdk_rejected'),
                  }
                : {
                    v: 1,
                    type: 'response',
                    id: msg.id,
                    plugin_id: msg.plugin_id,
                    version: msg.version,
                    digest: msg.digest,
                    ok: true,
                    result: res.result,
                  };
            frame.contentWindow?.postMessage(reply, '*');
          } catch (err: unknown) {
            const reply: HostToPluginMessage = {
              v: 1,
              type: 'error',
              id: msg.id,
              plugin_id: pluginId,
              ok: false,
              error: err instanceof Error ? err.message : 'host sdk bridge failed',
              code: 'bridge_error',
            };
            frame.contentWindow?.postMessage(reply, '*');
          }
        })();
      } catch (err: unknown) {
        // Malicious / spoofed / invalid messages: drop + surface soft error
        if (err instanceof HostSdkValidationError) {
          setError((prev) => prev || err.message);
        }
      }
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [pluginId]);

  return (
    <div className={className} data-plugin-frame={pluginId} data-plugin-slot={slot}>
      {loading && (
        <p className="p-2 text-xs text-[var(--muted)]">Loading sandboxed plugin UI…</p>
      )}
      {error && (
        <p className="p-2 text-xs text-red-600" role="alert">
          Plugin UI blocked: {error}
        </p>
      )}
      {srcdoc && (
        <iframe
          ref={iframeRef}
          title={`plugin:${pluginId}@${version}`}
          srcDoc={srcdoc}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          style={{
            width: '100%',
            height,
            border: '0',
            display: 'block',
            background: 'transparent',
          }}
          data-ev-plugin-sandbox="1"
        />
      )}
    </div>
  );
}
