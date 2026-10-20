import html2canvas from 'html2canvas';
import type { LegendInfo } from '../services/analyticsService';

export type MapExportDpi = 300 | 600;

interface ExportOptions {
  mapElement: HTMLElement;
  title?: string;
  placeName?: string;
  legend?: LegendInfo | null;
  filename?: string;
  /** Print resolution. Default 300. Scale ≈ dpi/96 for html2canvas. */
  dpi?: MapExportDpi;
}

/**
 * Capture the map pane and compose a print-style JPEG with
 * north arrow, scale bar, legend, grid (already on map), and title.
 */
export async function exportMapJpeg(options: ExportOptions): Promise<void> {
  const {
    mapElement,
    title = 'SAT EYE Map',
    placeName,
    legend,
    filename,
    dpi = 300,
  } = options;

  const cssDpi = 96;
  const scale = Math.max(2, dpi / cssDpi);

  // Prefer reading the live scale-bar label from map chrome when present.
  const scaleChrome = mapElement.querySelector('[data-map-chrome="scale"]');
  const liveScaleLabel =
    scaleChrome?.textContent?.replace(/\s+/g, ' ').trim() || null;

  const canvas = await html2canvas(mapElement, {
    useCORS: true,
    allowTaint: true,
    backgroundColor: '#ffffff',
    scale,
    logging: false,
  });

  const pad = Math.round(48 * (dpi / 300));
  const legendH = legend ? Math.round(110 * (dpi / 300)) : Math.round(24 * (dpi / 300));
  const headerH = Math.round(56 * (dpi / 300));
  const footerH = Math.round(56 * (dpi / 300));
  const out = document.createElement('canvas');
  out.width = canvas.width + pad * 2;
  out.height = canvas.height + headerH + footerH + legendH + pad;
  const ctx = out.getContext('2d');
  if (!ctx) return;

  const fontTitle = Math.round(28 * (dpi / 300));
  const fontSub = Math.round(16 * (dpi / 300));
  const fontBody = Math.round(12 * (dpi / 300));
  const fontSmall = Math.round(11 * (dpi / 300));

  // Paper background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, out.width, out.height);

  // Header
  ctx.fillStyle = '#0f2a22';
  ctx.fillRect(0, 0, out.width, headerH);
  ctx.fillStyle = '#ffffff';
  ctx.font = `bold ${fontTitle}px Sora, sans-serif`;
  ctx.fillText(title, pad, Math.round(headerH * 0.64));
  ctx.font = `${fontSub}px IBM Plex Sans, sans-serif`;
  ctx.fillStyle = '#a7c4b8';
  const subtitle = placeName ? `Location: ${placeName}` : 'Earth Observation';
  ctx.fillText(subtitle, out.width - pad - ctx.measureText(subtitle).width, Math.round(headerH * 0.64));

  // Map
  const mapY = headerH + Math.round(8 * (dpi / 300));
  ctx.drawImage(canvas, pad, mapY);

  // Border around map
  ctx.strokeStyle = '#1f6f54';
  ctx.lineWidth = Math.max(2, Math.round(2 * (dpi / 300)));
  ctx.strokeRect(pad, mapY, canvas.width, canvas.height);

  // North arrow (drawn in margin — always attached for export)
  const nx = out.width - pad - Math.round(36 * (dpi / 300));
  const ny = mapY + Math.round(24 * (dpi / 300));
  const arrowScale = dpi / 300;
  ctx.fillStyle = '#1f6f54';
  ctx.beginPath();
  ctx.moveTo(nx, ny);
  ctx.lineTo(nx + 14 * arrowScale, ny + 28 * arrowScale);
  ctx.lineTo(nx, ny + 20 * arrowScale);
  ctx.lineTo(nx - 14 * arrowScale, ny + 28 * arrowScale);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#0f2a22';
  ctx.font = `bold ${Math.round(14 * arrowScale)}px sans-serif`;
  ctx.fillText('N', nx - 5 * arrowScale, ny + 14 * arrowScale);

  let cursorY = mapY + canvas.height + Math.round(16 * (dpi / 300));

  // Legend
  if (legend) {
    ctx.fillStyle = '#14231c';
    ctx.font = `bold ${fontSub}px IBM Plex Sans, sans-serif`;
    ctx.fillText(`Legend — ${legend.label}`, pad, cursorY + 4);
    cursorY += Math.round(18 * (dpi / 300));

    const gradW = Math.min(Math.round(420 * (dpi / 300)), canvas.width);
    const grad = ctx.createLinearGradient(pad, 0, pad + gradW, 0);
    legend.stops.forEach((stop, i) => {
      grad.addColorStop(i / Math.max(legend.stops.length - 1, 1), stop.color);
    });
    ctx.fillStyle = grad;
    ctx.fillRect(pad, cursorY, gradW, Math.round(14 * (dpi / 300)));
    ctx.strokeStyle = '#94a3b8';
    ctx.strokeRect(pad, cursorY, gradW, Math.round(14 * (dpi / 300)));
    cursorY += Math.round(28 * (dpi / 300));

    ctx.fillStyle = '#5d7368';
    ctx.font = `${fontBody}px IBM Plex Mono, monospace`;
    ctx.fillText(
      `${legend.min.toFixed(2)}    ${legend.unit}    ${legend.max.toFixed(2)}`,
      pad,
      cursorY,
    );
    cursorY += Math.round(16 * (dpi / 300));
    ctx.font = `${fontSmall}px IBM Plex Sans, sans-serif`;
    ctx.fillText(legend.formula, pad, cursorY);
    cursorY += Math.round(18 * (dpi / 300));
  }

  // Explicit scale bar in export footer (in addition to any on-map chrome)
  const barW = Math.round(100 * (dpi / 300));
  const barH = Math.round(8 * (dpi / 300));
  const barY = out.height - Math.round(40 * (dpi / 300));
  ctx.strokeStyle = '#0f2a22';
  ctx.lineWidth = Math.max(2, Math.round(2 * (dpi / 300)));
  ctx.beginPath();
  ctx.moveTo(pad, barY);
  ctx.lineTo(pad, barY + barH);
  ctx.lineTo(pad + barW, barY + barH);
  ctx.lineTo(pad + barW, barY);
  ctx.stroke();
  ctx.fillStyle = '#0f2a22';
  ctx.font = `bold ${fontBody}px IBM Plex Sans, sans-serif`;
  const scaleLabel = liveScaleLabel || 'Scale (see map)';
  ctx.fillText(scaleLabel, pad + barW + Math.round(10 * (dpi / 300)), barY + barH);

  // Footer / DPI stamp
  ctx.fillStyle = '#5d7368';
  ctx.font = `${fontBody}px IBM Plex Sans, sans-serif`;
  const stamp = `Exported ${new Date().toISOString().slice(0, 19)}Z  ·  Grid: lat/lon  ·  ${dpi} DPI  ·  North arrow + scale bar`;
  ctx.fillText(stamp, pad, out.height - Math.round(12 * (dpi / 300)));

  const a = document.createElement('a');
  a.href = out.toDataURL('image/jpeg', dpi >= 600 ? 0.95 : 0.92);
  a.download =
    filename ||
    `sateye-map-${dpi}dpi-${Date.now()}.jpg`;
  a.click();
}
