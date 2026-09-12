import type { PredictResult, PredictTarget, SatelliteTrack } from './types';
import { formatInZone } from './time';

const W = 1600;
const H = 1100;
const MARGIN = { top: 72, right: 28, bottom: 28, left: 28 };

type BBox = { west: number; south: number; east: number; north: number };

function walkCoords(geom: GeoJSON.Geometry, visit: (lon: number, lat: number) => void) {
  const ring = (pts: number[][]) => pts.forEach((p) => visit(p[0], p[1]));
  if (geom.type === 'Point') visit(geom.coordinates[0], geom.coordinates[1]);
  else if (geom.type === 'MultiPoint' || geom.type === 'LineString') geom.coordinates.forEach((p) => visit(p[0], p[1]));
  else if (geom.type === 'MultiLineString' || geom.type === 'Polygon') geom.coordinates.forEach(ring);
  else if (geom.type === 'MultiPolygon') geom.coordinates.forEach((poly) => poly.forEach(ring));
  else if (geom.type === 'GeometryCollection') geom.geometries.forEach((g) => walkCoords(g, visit));
}

function bboxOfGeometry(geom: GeoJSON.Geometry): BBox | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  walkCoords(geom, (lon, lat) => {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  });
  if (!Number.isFinite(west)) return null;
  return { west, south, east, north };
}

function padBbox(b: BBox): BBox {
  const latSpan = Math.max(northSpan(b), 0.22);
  const lonSpan = Math.max(b.east - b.west, 0.22);
  const padLat = Math.max(1.6, latSpan * 1.4);
  const padLon = Math.max(2.0, lonSpan * 1.4);
  return {
    west: Math.max(-180, b.west - padLon),
    east: Math.min(180, b.east + padLon),
    south: Math.max(-85, b.south - padLat),
    north: Math.min(85, b.north + padLat),
  };
}

function northSpan(b: BBox) {
  return b.north - b.south;
}

function project(lon: number, lat: number, b: BBox) {
  const left = MARGIN.left;
  const top = MARGIN.top;
  const width = W - MARGIN.left - MARGIN.right;
  const height = H - MARGIN.top - MARGIN.bottom;
  const x = left + ((lon - b.west) / Math.max(b.east - b.west, 1e-6)) * width;
  const y = top + ((b.north - lat) / Math.max(b.north - b.south, 1e-6)) * height;
  return { x, y };
}

function inView(lon: number, lat: number, b: BBox) {
  return lon >= b.west && lon <= b.east && lat >= b.south && lat <= b.north;
}

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(x, y, w, h, r);
    return;
  }
  ctx.rect(x, y, w, h);
}

function dashFor(dash: string | undefined): number[] {
  if (dash === 'dashed') return [10, 7];
  if (dash === 'dotted') return [2, 7];
  return [];
}

function drawGeometry(
  ctx: CanvasRenderingContext2D,
  geom: GeoJSON.Geometry,
  b: BBox,
  style: { fill?: string; stroke?: string; width?: number },
) {
  const polys: number[][][][] =
    geom.type === 'Polygon'
      ? [geom.coordinates]
      : geom.type === 'MultiPolygon'
        ? geom.coordinates
        : geom.type === 'GeometryCollection'
          ? geom.geometries.flatMap((g) =>
              g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [],
            )
          : [];
  if (!polys.length && geom.type === 'Point') {
    const [lon, lat] = geom.coordinates;
    const p = project(lon, lat, b);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
    if (style.fill) {
      ctx.fillStyle = style.fill;
      ctx.fill();
    }
    if (style.stroke) {
      ctx.strokeStyle = style.stroke;
      ctx.lineWidth = style.width ?? 2;
      ctx.stroke();
    }
    return;
  }
  ctx.beginPath();
  for (const poly of polys) {
    for (const ring of poly) {
      ring.forEach((c, i) => {
        const p = project(c[0], c[1], b);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.closePath();
    }
  }
  if (style.fill) {
    ctx.fillStyle = style.fill;
    ctx.fill();
  }
  if (style.stroke) {
    ctx.strokeStyle = style.stroke;
    ctx.lineWidth = style.width ?? 2;
    ctx.stroke();
  }
}

function drawTrack(ctx: CanvasRenderingContext2D, track: SatelliteTrack, b: BBox) {
  const segs: { lon: number; lat: number }[][] = [];
  let cur: { lon: number; lat: number }[] = [];
  let prev: number | null = null;
  for (const s of track.samples) {
    if (prev !== null && Math.abs(s.lon - prev) > 180) {
      if (cur.length >= 2) segs.push(cur);
      cur = [];
    }
    cur.push(s);
    prev = s.lon;
  }
  if (cur.length >= 2) segs.push(cur);
  ctx.save();
  ctx.strokeStyle = track.color;
  ctx.lineWidth = 3.2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.setLineDash(dashFor(track.dash));
  for (const seg of segs) {
    for (let i = 1; i < seg.length; i += 1) {
      const a = seg[i - 1];
      const c = seg[i];
      if (!inView(a.lon, a.lat, b) && !inView(c.lon, c.lat, b)) continue;
      const p0 = project(a.lon, a.lat, b);
      const p1 = project(c.lon, c.lat, b);
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.lineTo(p1.x, p1.y);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function labelBox(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, color: string) {
  ctx.font = '600 12px Inter, system-ui, sans-serif';
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = 'rgba(7,12,18,0.82)';
  ctx.strokeStyle = `${color}99`;
  ctx.lineWidth = 1;
  ctx.beginPath();
  roundedRect(ctx, x, y - 10, w, 18, 3);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fillText(text, x + 5, y + 3);
  return { w, h: 18 };
}

let worldCache: GeoJSON.FeatureCollection | null = null;

async function loadWorld(): Promise<GeoJSON.FeatureCollection | null> {
  if (worldCache) return worldCache;
  try {
    const resp = await fetch('/world-countries-110m.geojson');
    if (!resp.ok) return null;
    worldCache = (await resp.json()) as GeoJSON.FeatureCollection;
    return worldCache;
  } catch {
    return null;
  }
}

export async function downloadAoiMapPng(opts: {
  target: PredictTarget;
  result: PredictResult | null;
  hiddenSats: Set<string>;
  hiddenPasses: Set<string>;
  timeZone: string;
}): Promise<void> {
  const { target, result, hiddenSats, hiddenPasses, timeZone } = opts;
  const raw = bboxOfGeometry(target.geometry) || {
    west: target.lon - 0.2,
    east: target.lon + 0.2,
    south: target.lat - 0.2,
    north: target.lat + 0.2,
  };
  const view = padBbox(raw);
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not create the map canvas.');

  ctx.fillStyle = '#0b1622';
  ctx.fillRect(0, 0, W, H);

  const world = await loadWorld();
  if (world) {
    for (const f of world.features) {
      if (!f.geometry) continue;
      drawGeometry(ctx, f.geometry, view, { fill: '#24384c', stroke: '#6f8aa3', width: 1 });
    }
  }

  ctx.save();
  ctx.strokeStyle = 'rgba(148,163,184,0.22)';
  ctx.lineWidth = 1;
  ctx.font = '500 10px Inter, system-ui, sans-serif';
  ctx.fillStyle = 'rgba(148,163,184,0.7)';
  const step = view.east - view.west > 8 ? 2 : 1;
  for (let lon = Math.ceil(view.west); lon < view.east; lon += step) {
    const a = project(lon, view.south, view);
    const c = project(lon, view.north, view);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(c.x, c.y);
    ctx.stroke();
    ctx.fillText(`${lon}°`, a.x + 3, H - 10);
  }
  for (let lat = Math.ceil(view.south); lat < view.north; lat += step) {
    const a = project(view.west, lat, view);
    const c = project(view.east, lat, view);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(c.x, c.y);
    ctx.stroke();
    ctx.fillText(`${lat}°`, 6, a.y - 3);
  }
  ctx.restore();

  const tracks = (result?.tracks || []).filter(
    (tr) => !hiddenSats.has(tr.satelliteId) && !hiddenPasses.has(tr.passId),
  );
  const passes = (result?.passes || []).filter(
    (p) => !hiddenSats.has(p.satelliteId) && !hiddenPasses.has(p.passId),
  );

  drawGeometry(ctx, target.geometry, view, { fill: 'rgba(251,191,36,0.32)', stroke: '#fbbf24', width: 3 });
  for (const tr of tracks) drawTrack(ctx, tr, view);

  const used: { x: number; y: number }[] = [];
  const far = (x: number, y: number) => used.every((u) => Math.hypot(u.x - x, u.y - y) > 40);

  for (const tr of tracks) {
    const pass = passes.find((p) => p.passId === tr.passId);
    const near = tr.samples.filter((s) => inView(s.lon, s.lat, view));
    if (!near.length) continue;
    const closest = near.reduce((best, s) => {
      const d = Math.hypot(s.lat - target.lat, s.lon - target.lon);
      const bd = Math.hypot(best.lat - target.lat, best.lon - target.lon);
      return d < bd ? s : best;
    });
    const nameAt = project(closest.lon, closest.lat, view);
    if (far(nameAt.x, nameAt.y)) {
      labelBox(ctx, nameAt.x + 10, nameAt.y - 14, tr.satelliteName, tr.color);
      used.push({ x: nameAt.x, y: nameAt.y });
    }
    const timed = [
      near[0],
      near[Math.floor(near.length / 2)],
      near[near.length - 1],
    ].filter(Boolean);
    if (pass) {
      timed[0] = { ...timed[0], utcMs: Date.parse(pass.startUtc) };
      timed[timed.length - 1] = { ...timed[timed.length - 1], utcMs: Date.parse(pass.endUtc) };
    }
    for (const s of timed) {
      const q = project(s.lon, s.lat, view);
      if (!far(q.x, q.y)) continue;
      labelBox(ctx, q.x + 10, q.y + 8, formatInZone(new Date(s.utcMs).toISOString(), timeZone, false), tr.color);
      used.push({ x: q.x, y: q.y });
    }
  }

  ctx.fillStyle = '#e5eef6';
  ctx.font = '700 20px Inter, system-ui, sans-serif';
  ctx.fillText(`SatPass — ${target.name}`, 28, 32);
  ctx.font = '500 13px Inter, system-ui, sans-serif';
  ctx.fillStyle = '#94a3b8';
  const range =
    passes.length > 0
      ? `${formatInZone(passes[0].startUtc, timeZone, false)}  →  ${formatInZone(passes[passes.length - 1].endUtc, timeZone, false)}`
      : 'No intersecting passes in this window';
  ctx.fillText(`${range}   ·   AOI-focused map`, 28, 54);

  const sats = new Map<string, { name: string; color: string }>();
  for (const p of passes) sats.set(p.satelliteId, { name: p.satelliteName, color: p.color });
  if (!sats.size) {
    for (const tr of tracks) sats.set(tr.satelliteId, { name: tr.satelliteName, color: tr.color });
  }
  const legend = [{ name: `Target AOI — ${target.name}`, color: '#fbbf24' }, ...[...sats.values()]];
  const lineH = 20;
  const boxH = 36 + legend.length * lineH;
  const boxW = Math.min(
    360,
    28 + legend.reduce((m, it) => Math.max(m, ctx.measureText(it.name).width), 120),
  );
  const lx = W - boxW - 24;
  const ly = 78;
  ctx.fillStyle = 'rgba(7,12,18,0.88)';
  ctx.strokeStyle = 'rgba(255,255,255,0.16)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  roundedRect(ctx, lx, ly, boxW, boxH, 6);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = '#cbd5e1';
  ctx.font = '700 11px Inter, system-ui, sans-serif';
  ctx.fillText('LEGEND', lx + 12, ly + 20);
  ctx.font = '500 12px Inter, system-ui, sans-serif';
  legend.forEach((it, i) => {
    const y = ly + 38 + i * lineH;
    ctx.fillStyle = it.color;
    ctx.fillRect(lx + 12, y - 8, 12, 12);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(it.name, lx + 32, y + 2);
  });

  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png');
  a.download = `satpass-aoi-map-${target.name.replace(/[^\w.-]+/g, '_')}.png`;
  a.click();
}
