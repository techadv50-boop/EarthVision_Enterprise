/** Detect overlay mime from raw base64 (PNG / JPEG / WebP). */
export function overlayMimeFromBase64(b64: string): string {
  const raw = b64.includes(',') ? b64.split(',', 1)[1] : b64;
  const head = raw.slice(0, 16);
  if (head.startsWith('/9j/')) return 'image/jpeg';
  if (head.startsWith('UklGR')) return 'image/webp';
  if (head.startsWith('iVBOR')) return 'image/png';
  // Default: WebP interactive overlays; PNG still works if mis-detected
  return 'image/png';
}

export function toOverlayDataUrl(b64: string): string {
  if (!b64) return '';
  if (b64.startsWith('data:')) return b64;
  return `data:${overlayMimeFromBase64(b64)};base64,${b64}`;
}

/** Interactive map preview edge — keep small for slow links / Cloudflare. */
export const INTERACTIVE_PREVIEW_SIZE = 512;

/**
 * True/False Color (and other RGB composites) need a larger grid so the overlay
 * is not stretched soft across a full S2/Landsat footprint on the map.
 * Keep ≤2048 so render stays under the ~55s server budget (avoids 504).
 * Sharp Eye-On XYZ tiles stay visible under this overlay — use Swipe to compare.
 */
export const COMPOSITE_PREVIEW_SIZE = 2048;
