import { api } from './api';
import type { PluginSlot } from './pluginService';

export interface ToolPlacementNode {
  id: string;
  plugin_id: string;
  category_id: string;
  display_name: string;
  description?: string | null;
  icon?: string | null;
  sort_order: number;
  execution_slot: PluginSlot | string;
  visible: boolean;
  enabled: boolean;
  plugin_active?: boolean;
  plugin_version?: string | null;
  plugin_digest?: string | null;
  activation_status?: string;
  installation_status?: string;
  in_active_tree?: boolean;
  name?: string;
  version?: string | null;
  digest?: string | null;
  permissions?: string[];
  frontend_slot?: string;
}

export interface ToolCategoryNode {
  id: string;
  name: string;
  parent_id: string | null;
  sort_order: number;
  collapsed_default?: boolean;
  placements: ToolPlacementNode[];
  children: ToolCategoryNode[];
}

export interface ToolTreeResponse {
  ok: boolean;
  plugin_first?: boolean;
  supported_slots?: string[];
  max_category_depth?: number;
  empty: boolean;
  roots: ToolCategoryNode[];
  message?: string | null;
  error?: string;
}

export const toolTreeService = {
  async getTree(): Promise<ToolTreeResponse> {
    const { data } = await api.get('/tools/tree');
    return data;
  },

  async getManageTree(): Promise<ToolTreeResponse> {
    const { data } = await api.get('/tools/tree/manage');
    return data;
  },

  async activeForSlot(slot: PluginSlot): Promise<{ ok?: boolean; plugins: ToolPlacementNode[] }> {
    const { data } = await api.get(`/tools/slots/${slot}/active`);
    return data;
  },

  async createCategory(body: {
    name: string;
    parent_id?: string | null;
    sort_order?: number;
  }): Promise<Record<string, unknown>> {
    const { data } = await api.post('/tools/categories', body);
    return data;
  },

  async renameCategory(id: string, name: string): Promise<Record<string, unknown>> {
    const { data } = await api.patch(`/tools/categories/${id}`, { name });
    return data;
  },

  async moveCategory(
    id: string,
    body: { parent_id?: string | null; sort_order?: number },
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/tools/categories/${id}/move`, body);
    return data;
  },

  async reorderCategories(
    orderedIds: string[],
    parentId: string | null,
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post('/tools/categories/reorder', {
      ordered_ids: orderedIds,
      parent_id: parentId,
    });
    return data;
  },

  async deleteCategory(id: string): Promise<Record<string, unknown>> {
    const { data } = await api.delete(`/tools/categories/${id}`);
    return data;
  },

  async upsertPlacement(body: {
    plugin_id: string;
    category_id: string;
    display_name: string;
    execution_slot: string;
    description?: string;
    icon?: string;
    sort_order?: number;
    visible?: boolean;
    enabled?: boolean;
  }): Promise<Record<string, unknown>> {
    const { data } = await api.post('/tools/placements', body);
    return data;
  },

  async movePlacement(
    id: string,
    body: { category_id: string; sort_order?: number },
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/tools/placements/${id}/move`, body);
    return data;
  },

  async reorderPlacements(
    categoryId: string,
    orderedIds: string[],
  ): Promise<Record<string, unknown>> {
    const { data } = await api.post(`/tools/placements/reorder/${categoryId}`, {
      ordered_ids: orderedIds,
    });
    return data;
  },

  async deletePlacement(id: string): Promise<Record<string, unknown>> {
    const { data } = await api.delete(`/tools/placements/${id}`);
    return data;
  },

  async snapshot(label: string, note?: string): Promise<Record<string, unknown>> {
    const { data } = await api.post('/tools/tree/snapshot', { label, note });
    return data;
  },

  async revisions(): Promise<{ ok: boolean; revisions: Array<Record<string, unknown>> }> {
    const { data } = await api.get('/tools/tree/revisions');
    return data;
  },

  async exportTree(): Promise<ToolTreeResponse> {
    const { data } = await api.get('/tools/tree/export');
    return data;
  },
};
