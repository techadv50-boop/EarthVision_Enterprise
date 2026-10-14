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

export const pluginService = {
  async listAdmin(): Promise<{ ok: boolean; plugins: PluginRecord[] }> {
    const { data } = await api.get('/admin/plugins');
    return data;
  },

  async listActive(slot?: PluginSlot): Promise<{ plugins: PluginRecord[] }> {
    const { data } = await api.get('/plugins/active', {
      params: slot ? { slot } : undefined,
    });
    return data;
  },

  async listSlots(): Promise<{ supported_slots: PluginSlot[]; notes: string }> {
    const { data } = await api.get('/plugins/slots');
    return data;
  },

  async upload(file: File): Promise<{ ok?: boolean; staging_id?: string; error?: string }> {
    const body = new FormData();
    body.append('file', file);
    const { data } = await api.post('/admin/plugins/upload', body);
    return data;
  },

  async validateUpload(file: File): Promise<Record<string, unknown>> {
    const body = new FormData();
    body.append('file', file);
    const { data } = await api.post('/admin/plugins/validate-upload', body);
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
