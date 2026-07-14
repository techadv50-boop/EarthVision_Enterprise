import { api } from './api';

export interface Bookmark {
  id: string;
  name: string;
  description?: string | null;
  longitude: number;
  latitude: number;
  height: number;
  heading: number;
  pitch: number;
  roll: number;
  created_at: string;
}

export const bookmarkService = {
  async list(): Promise<Bookmark[]> {
    const { data } = await api.get<Bookmark[]>('/bookmarks');
    return data;
  },

  async create(payload: Omit<Bookmark, 'id' | 'created_at'>) {
    const { data } = await api.post<Bookmark>('/bookmarks', payload);
    return data;
  },

  async remove(id: string) {
    await api.delete(`/bookmarks/${id}`);
  },
};
