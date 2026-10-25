import { api } from './api';

async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export type HostLibraryPackage = {
  source?: string;
  filename?: string;
  spec?: string;
  installed_at?: string;
  actor?: string;
};

export type HostLibrariesStatus = {
  ok?: boolean;
  extras_dir?: string;
  on_sys_path?: boolean;
  pip_allowlist?: string[];
  pip_from_index_enabled?: boolean;
  packages?: Record<string, HostLibraryPackage>;
  notes?: string;
  error?: string;
};

export const hostLibraryService = {
  async list(): Promise<HostLibrariesStatus> {
    const { data } = await api.get('/admin/host-libraries');
    return data;
  },

  async uploadWheels(files: File[]): Promise<Record<string, unknown>> {
    const payload = await Promise.all(
      files.map(async (file) => ({
        filename: file.name,
        content_base64: await fileToBase64(file),
      })),
    );
    const { data } = await api.post('/admin/host-libraries/upload', { files: payload });
    return data;
  },

  async pipInstall(packageName: string, version?: string): Promise<Record<string, unknown>> {
    const { data } = await api.post('/admin/host-libraries/pip-install', {
      package: packageName,
      version: version || null,
    });
    return data;
  },

  async uninstall(name: string): Promise<Record<string, unknown>> {
    const { data } = await api.post('/admin/host-libraries/uninstall', { name });
    return data;
  },
};
