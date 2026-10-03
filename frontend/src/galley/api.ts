import api from "@/services/api";
import type { AxiosError } from "axios";
import type { Galley, IconAsset, Journal } from "./types";

export type Account = {
  id: string;
  name: string;
  email: string;
  role: "admin" | "user";
  status: "pending" | "approved" | "restricted";
};

export type GalleyRecord = {
  galley: Galley;
  ownerId: string;
  ownerName: string;
  ownerEmail: string;
};

function detail(error: unknown): string {
  const ax = error as AxiosError<{ detail?: unknown }>;
  const body = ax.response?.data?.detail;
  if (typeof body === "string") return body;
  return ax.message || "Request failed";
}

async function unwrap<T>(work: Promise<{ data: T }>): Promise<T> {
  try {
    const { data } = await work;
    return data;
  } catch (error) {
    throw new Error(detail(error));
  }
}

export function journals() {
  return unwrap<Journal[]>(api.get("/galley/journals"));
}

export function saveJournal(journal: Journal) {
  return unwrap<Journal>(api.post("/galley/journals", journal));
}

export function deleteJournal(id: string) {
  return unwrap<{ ok: boolean }>(api.delete(`/galley/journals/${id}`));
}

export function galleys() {
  return unwrap<GalleyRecord[]>(api.get("/galley/galleys"));
}

export function createGalley(galley: Galley) {
  return unwrap<Galley>(api.post("/galley/galleys", galley));
}

export function updateGalley(galley: Galley) {
  return unwrap<Galley>(api.put(`/galley/galleys/${galley.id}`, galley));
}

export function deleteGalley(id: string) {
  return unwrap<{ ok: boolean }>(api.delete(`/galley/galleys/${id}`));
}

export function openAccess() {
  return unwrap<{ icon: IconAsset | null }>(api.get("/galley/settings/open-access"));
}

export function saveOpenAccess(icon: IconAsset | null) {
  return unwrap<{ ok: boolean }>(api.put("/galley/settings/open-access", { icon }));
}

export function readEquation(dataUrl: string) {
  return unwrap<{ text: string }>(api.post("/galley/ocr", { dataUrl }));
}
