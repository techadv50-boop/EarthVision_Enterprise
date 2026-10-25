/**
 * Versioned Host SDK contract for sandboxed plugin iframes (RC).
 *
 * Plugins must NOT import Host Shell modules, read auth tokens, call
 * unrestricted APIs, or touch Leaflet. Communication is postMessage only.
 */

export const PLUGIN_HOST_SDK_PROTOCOL = 1 as const;
/** 1.3: permanent map presentation + host.clearMapLayer (additive). */
export const PLUGIN_HOST_SDK_VERSION = '1.3.0';

export type HostSdkMethod =
  | 'host.meta'
  | 'host.getSynthetic'
  | 'host.resize'
  | 'host.getAoiBounds'
  | 'host.setAnalysisResult'
  | 'host.getAnalysisResult'
  | 'host.getSceneContext'
  | 'host.renderTrueColor'
  | 'host.clearMapLayer'
  | 'host.exportGeotiff'
  | 'host.exportMapJpeg';

const ALLOWED_METHODS = new Set<string>([
  'host.meta',
  'host.getSynthetic',
  'host.resize',
  'host.getAoiBounds',
  'host.setAnalysisResult',
  'host.getAnalysisResult',
  'host.getSceneContext',
  'host.renderTrueColor',
  'host.clearMapLayer',
  'host.exportGeotiff',
  'host.exportMapJpeg',
]);

const FORBIDDEN_METHODS = new Set<string>([
  'host.getAuthToken',
  'host.getSession',
  'host.fetch',
  'host.leaflet',
  'host.map',
  'host.eval',
  'host.import',
  'host.admin',
  'host.database',
]);

export type PluginToHostMessage =
  | {
      v: typeof PLUGIN_HOST_SDK_PROTOCOL;
      type: 'ready';
      plugin_id: string;
      version: string;
      digest: string;
    }
  | {
      v: typeof PLUGIN_HOST_SDK_PROTOCOL;
      type: 'request';
      id: string;
      plugin_id: string;
      version: string;
      digest: string;
      method: string;
      params: Record<string, unknown>;
    };

export type HostToPluginMessage =
  | {
      v: typeof PLUGIN_HOST_SDK_PROTOCOL;
      type: 'response';
      id: string;
      plugin_id: string;
      version: string;
      digest: string;
      ok: true;
      result: unknown;
    }
  | {
      v: typeof PLUGIN_HOST_SDK_PROTOCOL;
      type: 'error';
      id: string | null;
      plugin_id: string | null;
      ok: false;
      error: string;
      code: string;
    };

export class HostSdkValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'HostSdkValidationError';
  }
}

function hasSecretKey(obj: Record<string, unknown>): boolean {
  return Object.keys(obj).some((k) => {
    const lk = k.toLowerCase();
    return (
      lk.includes('token') ||
      lk.includes('password') ||
      lk.includes('secret') ||
      lk.includes('authorization') ||
      lk.includes('cookie')
    );
  });
}

export function validatePluginMessage(data: unknown): PluginToHostMessage {
  if (!data || typeof data !== 'object') {
    throw new HostSdkValidationError('message must be an object');
  }
  const msg = data as Record<string, unknown>;
  if (msg.v !== PLUGIN_HOST_SDK_PROTOCOL) {
    throw new HostSdkValidationError('unsupported Host SDK protocol version');
  }
  if (msg.type !== 'ready' && msg.type !== 'request') {
    throw new HostSdkValidationError(`unsupported message type: ${String(msg.type)}`);
  }
  if (typeof msg.plugin_id !== 'string' || !msg.plugin_id) {
    throw new HostSdkValidationError('plugin_id required');
  }
  if (typeof msg.version !== 'string' || !msg.version) {
    throw new HostSdkValidationError('version required');
  }
  if (typeof msg.digest !== 'string' || !msg.digest.startsWith('sha256:')) {
    throw new HostSdkValidationError('digest must be sha256:...');
  }

  if (msg.type === 'ready') {
    return {
      v: PLUGIN_HOST_SDK_PROTOCOL,
      type: 'ready',
      plugin_id: msg.plugin_id,
      version: msg.version,
      digest: msg.digest,
    };
  }

  if (typeof msg.id !== 'string' || !msg.id) {
    throw new HostSdkValidationError('request id required');
  }
  if (typeof msg.method !== 'string' || !msg.method) {
    throw new HostSdkValidationError('method required');
  }
  if (FORBIDDEN_METHODS.has(msg.method)) {
    throw new HostSdkValidationError(`forbidden Host SDK method: ${msg.method}`);
  }
  if (!ALLOWED_METHODS.has(msg.method)) {
    throw new HostSdkValidationError(`unknown Host SDK method: ${msg.method}`);
  }
  const params =
    msg.params == null
      ? {}
      : typeof msg.params === 'object' && !Array.isArray(msg.params)
        ? (msg.params as Record<string, unknown>)
        : null;
  if (!params) {
    throw new HostSdkValidationError('params must be an object');
  }
  if (hasSecretKey(params)) {
    throw new HostSdkValidationError('params must not include secrets');
  }

  return {
    v: PLUGIN_HOST_SDK_PROTOCOL,
    type: 'request',
    id: msg.id,
    plugin_id: msg.plugin_id,
    version: msg.version,
    digest: msg.digest,
    method: msg.method,
    params,
  };
}

export function assertIdentityMatch(
  msg: PluginToHostMessage,
  expected: { pluginId: string; version: string; digest: string },
): void {
  if (msg.plugin_id !== expected.pluginId) {
    throw new HostSdkValidationError('plugin_id mismatch (possible spoof)');
  }
  if (msg.version !== expected.version) {
    throw new HostSdkValidationError('version mismatch vs active pin');
  }
  if (msg.digest !== expected.digest) {
    throw new HostSdkValidationError('digest mismatch vs active pin');
  }
}
