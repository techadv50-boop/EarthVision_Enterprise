import html2canvas from 'html2canvas';
import type { LegendInfo } from '../services/analyticsService';

interface ExportOptions {
  mapElement: HTMLElement;
  title?: string;
  placeName?: string;
  legend?: LegendInfo | null;
  filename?: string;
}

/**
 * Capture the map pane and compose a print-style JPEG with
 * north arrow, scale note, legend, grid (already on map), and title.
 */
export async function exportMapJpeg(options: ExportOptions): Promise<void> {
  const { mapElement, title = 'SAT EYE Map', placeName, legend, filename } = options;

  const canvas = await html2canvas(mapElement, {
    useCORS: true,
    allowTaint: true,
    backgroundColor: '#ffffff',
    scale: 2,
    logging: false,
  });

  const pad = 48;
  const legendH = legend ? 110 : 24;
  const headerH = 56;
  const footerH = 36;
  const out = document.createElement('canvas');
  out.width = canvas.width + pad * 2;
  out.height = canvas.height + headerH + footerH + legendH + pad;
  const ctx = out.getContext('2d');
  if (!ctx) return;

  // Paper background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, out.width, out.height);

  // Header
  ctx.fillStyle = '#0f2a22';
  ctx.fillRect(0, 0, out.width, headerH);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 28px Sora, sans-serif';
  ctx.fillText(title, pad, 36);
  ctx.font = '16px IBM Plex Sans, sans-serif';
  ctx.fillStyle = '#a7c4b8';
  const subtitle = placeName ? `Location: ${placeName}` : 'Earth Observation';
  ctx.fillText(subtitle, out.width - pad - ctx.measureText(subtitle).width, 36);

  // Map
  const mapY = headerH + 8;
  ctx.drawImage(canvas, pad, mapY);

  // Border around map
  ctx.strokeStyle = '#1f6f54';
  ctx.lineWidth = 2;
  ctx.strokeRect(pad, mapY, canvas.width, canvas.height);

  // North arrow (drawn in margin)
  const nx = out.width - pad - 36;
  const ny = mapY + 24;
  ctx.fillStyle = '#1f6f54';
  ctx.beginPath();
  ctx.moveTo(nx, ny);
  ctx.lineTo(nx + 14, ny + 28);
  ctx.lineTo(nx, ny + 20);
  ctx.lineTo(nx - 14, ny + 28);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#0f2a22';
  ctx.font = 'bold 14px sans-serif';
  ctx.fillText('N', nx - 5, ny + 14);

  let cursorY = mapY + canvas.height + 16;

  // Legend
  if (legend) {
    ctx.fillStyle = '#14231c';
    ctx.font = 'bold 16px IBM Plex Sans, sans-serif';
    ctx.fillText(`Legend — ${legend.label}`, pad, cursorY + 4);
    cursorY += 18;

    const gradW = Math.min(420, canvas.width);
    const grad = ctx.createLinearGradient(pad, 0, pad + gradW, 0);
    legend.stops.forEach((stop, i) => {
      grad.addColorStop(i / Math.max(legend.stops.length - 1, 1), stop.color);
    });
    ctx.fillStyle = grad;
    ctx.fillRect(pad, cursorY, gradW, 14);
    ctx.strokeStyle = '#94a3b8';
    ctx.strokeRect(pad, cursorY, gradW, 14);
    cursorY += 28;

    ctx.fillStyle = '#5d7368';
    ctx.font = '12px IBM Plex Mono, monospace';
    ctx.fillText(
      `${legend.min.toFixed(2)}    ${legend.unit}    ${legend.max.toFixed(2)}`,
      pad,
      cursorY,
    );
    cursorY += 16;
    ctx.font = '11px IBM Plex Sans, sans-serif';
    ctx.fillText(legend.formula, pad, cursorY);
    cursorY += 18;
  }

  // Footer / scale note
  ctx.fillStyle = '#5d7368';
  ctx.font = '12px IBM Plex Sans, sans-serif';
  const stamp = `Exported ${new Date().toISOString().slice(0, 19)}Z  ·  Grid: lat/lon  ·  Scale bar shown on map`;
  ctx.fillText(stamp, pad, out.height - 16);

  const a = document.createElement('a');
  a.href = out.toDataURL('image/jpeg', 0.92);
  a.download = filename || `sateye-map-${Date.now()}.jpg`;
  a.click();
}
