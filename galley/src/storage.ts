import type { BodyBlock, Galley, IconAsset, Journal, Store } from "./types";
import { cloneIcons, newId } from "./metrics";
import { parseReference } from "./references";

const KEY = "galley-composer-v1";

export const EMPTY_STORE: Store = { openAccessIcon: null, journals: [], galleys: [] };

export function loadStore(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return EMPTY_STORE;
    const parsed = JSON.parse(raw) as Store;
    if (!parsed || !Array.isArray(parsed.journals) || !Array.isArray(parsed.galleys)) return EMPTY_STORE;
    return { ...parsed, galleys: parsed.galleys.map(normalizeGalley) };
  } catch {
    return EMPTY_STORE;
  }
}

export function saveStore(store: Store): void {
  localStorage.setItem(KEY, JSON.stringify(store));
}

export function blankAuthor(): Galley["authors"][number] {
  return { id: newId(), name: "", affiliation: "", corresponding: false, email: "" };
}

export function newGalley(journal: Journal): Galley {
  return {
    id: newId(),
    journalId: journal.id,
    title: "",
    authors: [{ ...blankAuthor(), corresponding: true }],
    volume: "",
    issue: "",
    startPage: "",
    received: "",
    revised: "",
    accepted: "",
    published: "",
    abstract: "",
    keywords: "",
    topIcons: cloneIcons(journal.topIcons),
    partnerIcons: cloneIcons(journal.partnerIcons),
    blocks: [{ id: newId(), type: "section", heading: "Introduction:", text: "" }],
    references: [],
    referenceStyle: "ieee",
    updatedAt: Date.now(),
  };
}

function normalizeGalley(galley: Galley): Galley {
  const blocks: BodyBlock[] = [];
  const recovered: string[] = [];
  const source = galley.blocks || [];
  for (let index = 0; index < source.length; index += 1) {
    const block = source[index];
    if (block.type === "heading" && /^references\b/i.test(block.text)) {
      const next = source[index + 1];
      if (next?.type === "paragraph" && next.text.trim()) {
        recovered.push(...next.text.split(/\n+/).map((line) => line.trim()).filter(Boolean));
        index += 1;
      }
      continue;
    }
    if (block.type === "heading") {
      const next = source[index + 1];
      if (next?.type === "paragraph") {
        blocks.push({ id: block.id, type: "section", heading: block.text, text: next.text });
        index += 1;
      } else {
        blocks.push({ id: block.id, type: "section", heading: block.text, text: "" });
      }
      continue;
    }
    if (block.type === "paragraph") {
      blocks.push({ id: newId(), type: "section", heading: "", text: block.text });
      continue;
    }
    blocks.push(block);
  }
  return {
    ...galley,
    blocks: blocks.length ? blocks : [{ id: newId(), type: "section", heading: "Introduction:", text: "" }],
    references: galley.references?.length ? galley.references : recovered.map(parseReference),
    referenceStyle: galley.referenceStyle || "ieee",
  };
}

export async function readIconFile(file: File, maxHeight: number): Promise<IconAsset> {
  const dataUrl = await fileToDataUrl(file);
  const size = await measure(dataUrl);
  const height = Math.min(maxHeight, size.height || maxHeight);
  const width = Math.max(12, Math.round(((size.width || height) / (size.height || height)) * height));
  return { id: newId(), name: file.name, dataUrl, widthPx: width, heightPx: height };
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function measure(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => resolve({ width: maxFallback(dataUrl), height: 40 });
    image.src = dataUrl;
  });
}

function maxFallback(dataUrl: string): number {
  return dataUrl.startsWith("data:image/jpeg") ? 160 : 120;
}

export async function fetchIcon(path: string, name: string, maxHeight: number): Promise<IconAsset> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  const blob = await response.blob();
  const file = new File([blob], name, { type: blob.type || "image/png" });
  return readIconFile(file, maxHeight);
}
