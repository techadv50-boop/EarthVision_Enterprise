import { api } from './api';

export interface FolderRepoPublic {
  id: string;
  label: string;
  repository_url: string;
  enabled: boolean;
  sort_order: number;
}

export interface FolderRepoAdmin extends FolderRepoPublic {
  has_api_key?: boolean;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FolderRepoCreatePayload {
  label: string;
  repository_url: string;
  api_key: string;
  notes?: string;
  enabled?: boolean;
  sort_order?: number;
}

export interface FolderRepoUpdatePayload {
  label?: string;
  repository_url?: string;
  api_key?: string;
  notes?: string | null;
  enabled?: boolean;
  sort_order?: number;
}

export interface FolderFileEntry {
  path: string;
  name?: string | null;
  size?: number | null;
}

export const folderRepoService = {
  async listEnabled(): Promise<FolderRepoPublic[]> {
    const { data } = await api.get<{ total: number; items: FolderRepoPublic[] }>(
      '/folder-repos',
    );
    return data.items;
  },

  async listAdmin(): Promise<FolderRepoAdmin[]> {
    const { data } = await api.get<{ total: number; items: FolderRepoAdmin[] }>(
      '/folder-repos/admin',
    );
    return data.items;
  },

  async create(payload: FolderRepoCreatePayload): Promise<FolderRepoAdmin> {
    const { data } = await api.post<FolderRepoAdmin>('/folder-repos/admin', payload);
    return data;
  },

  async update(id: string, payload: FolderRepoUpdatePayload): Promise<FolderRepoAdmin> {
    const { data } = await api.patch<FolderRepoAdmin>(`/folder-repos/admin/${id}`, payload);
    return data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/folder-repos/admin/${id}`);
  },

  async listDates(id: string): Promise<string[]> {
    const { data } = await api.get<{ dates: string[] }>(`/folder-repos/${id}/dates`);
    return data.dates || [];
  },

  async listFiles(id: string, date: string): Promise<FolderFileEntry[]> {
    const { data } = await api.get<{ files: FolderFileEntry[] }>(`/folder-repos/${id}/files`, {
      params: { date },
    });
    return data.files || [];
  },

  /** Trigger browser download via authenticated API (Bearer key stays on server). */
  async downloadFile(id: string, date: string, path: string): Promise<void> {
    const { data } = await api.get<Blob>(`/folder-repos/${id}/file`, {
      params: { date, path },
      responseType: 'blob',
    });
    const filename = path.split('/').pop() || 'download.bin';
    const url = window.URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  },
};
