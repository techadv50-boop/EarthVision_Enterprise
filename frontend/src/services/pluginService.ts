import { api } from './api';

export type PluginActivationStatus = 'inactive' | 'active' | 'disabled';
export type PluginInstallationStatus = 'not_installed' | 'installed';

export type PluginSlot =
  | 'left_toolbar'
  | 'right_analysis_panel'
  | 'map_overlay'
  | 'results_panel';

export interface PluginRecord {
  plugin_id: string;
  name: string;
  description: string;
  version: string | null;
  compatible_host_api: string;
  backend_entrypoint: string;
  frontend_slot: PluginSlot;
  permissions: string[];
  installation_status: PluginInstallationStatus;
  activation_status: PluginActivationStatus;
  previous_version?: string | null;
  digest?: string | null;
  installed_versions?: string[];
  updated_at?: string;
}

export interface PluginAuditEvent {
  ts?: string;
  action?: string;
  ok?: boolean;
  plugin_id?: string;
  version?: string;
  error?: string;
  actor?: string;
  [key: string]: unknown;
}

export interface PluginFrontendManifest {
  ok?: boolean;
  plugin_id: string;
  name?: string;
  version: string;
  digest: string;
  frontend_slot: PluginSlot;
  ui_strategy?: string;
  entry_html?: string;
  permissions?: string[];
  compatible_host_api?: string;
  host_sdk_version?: string;
  host_sdk_protocol?: number;
  loading_model?: string;
  signature_status?: string;
  ui_files?: string[];
}

export interface PluginSystemHealth {
  ok?: boolean;
  host_sdk_version?: string;
  host_sdk_protocol?: number;
  pack_host_api_version?: string;
  trust_profile?: string;
  require_signature?: boolean;
  worker?: {
    configured?: boolean;
    available?: boolean;
    isolated?: boolean;
    process_isolation?: string;
    auth_configured?: boolean;
    skipped?: boolean;
    error?: string;
  };
  active_count?: number;
  active_plugins?: Array<{
    plugin_id?: string;
    version?: string;
    digest?: string;
    frontend_slot?: string;
    compatible_host_api?: string;
  }>;
  loading_model?: string;
}

export const pluginService = {
  async listAdmin(): Promise<{ ok: boolean; plugins: PluginRecord[] }> {
    const { data } = await api.get('/admin/plugins');
    return data;
  },

  async health(): Promise<PluginSystemHealth> {
    const { data } = await api.get('/admin/plugins/health');
    return data;
  },

  async listActive(slot?: PluginSlot): Promise<{ plugins: PluginRecord[] }> {
    const { data } = await api.get('/plugins/active', {
      params: slot ? { slot } : undefined,
    });
    return data;
  },

  async listSlots(): Promise<{
    supported_slots: PluginSlot[];
    notes: string;
    loading_model?: string;
    plugin_host_sdk_version?: string;
  }> {
    const { data } = await api.get('/plugins/slots');
    return data;
  },

  async frontendManifest(pluginId: string): Promise<PluginFrontendManifest> {
    const { data } = await api.get(`/plugins/${pluginId}/frontend`);
    return data;
  },

  async uiAssetText(pluginId: string, assetPath: string): Promise<string> {
    const { data } = await api.get(`/plugins/${pluginId}/ui/${assetPath}`, {
      responseType: 'text',
      transformResponse: [(d) => d],
    });
    return typeof data === 'string' ? data : String(data ?? '');
  },

  async hostSdk(
    pluginId: string,
    body: {
      v: number;
      type: string;
      id: string;
      plugin_id: string;
      version: string;
      digest: string;
      method: string;
      params: Record<string, unknown>;
    },
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/plugins/${pluginId}/host-sdk`, body);
    return data;
  },

  async upload(file: File): Promise<{ ok?: boolean; staging_id?: string; error?: string }> {
    const body = new FormData();
    body.append('file', file);
    const { data } = await api.post('/admin/plugins/upload', body, {
      // Let the browser set multipart boundary (api default JSON Content-Type breaks this).
      headers: { 'Content-Type': undefined as unknown as string },
    });
    return data;
  },

  async validateUpload(file: File): Promise<Record<string, unknown>> {
    const body = new FormData();
    body.append('file', file);
    const { data } = await api.post('/admin/plugins/validate-upload', body, {
      headers: { 'Content-Type': undefined as unknown as string },
    });
    return data;
  },

  async validateStaging(stagingId: string): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/admin/plugins/staging/${stagingId}/validate`);
    return data;
  },

  async installStaging(
    stagingId: string,
    expectedDigest: string,
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post('/admin/plugins/install', {
      staging_id: stagingId,
      expected_digest: expectedDigest,
      confirm: 'install',
    });
    return data;
  },

  async activate(pluginId: string, version: string): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/admin/plugins/${pluginId}/activate`, {
      confirm: 'activate',
      version,
    });
    return data;
  },

  async disable(pluginId: string): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/admin/plugins/${pluginId}/disable`, {
      confirm: 'disable',
    });
    return data;
  },

  async rollback(pluginId: string, to: string): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/admin/plugins/${pluginId}/rollback`, {
      confirm: 'rollback',
      to,
    });
    return data;
  },

  async versions(pluginId: string): Promise<{ versions: Array<{ version: string; digest?: string; active?: boolean }> }> {
    const { data } = await api.get(`/admin/plugins/${pluginId}/versions`);
    return data;
  },

  async audit(limit = 50): Promise<{ events: PluginAuditEvent[] }> {
    const { data } = await api.get('/admin/plugins/audit', { params: { limit } });
    return data;
  },

  async synthetic(pluginId: string): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/plugins/${pluginId}/synthetic`);
    return data;
  },
};
