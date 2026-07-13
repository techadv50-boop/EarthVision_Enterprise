import { Compass, MousePointer2, Ruler } from 'lucide-react';
import { useMapStore } from '../store/mapStore';

export function StatusBar() {
  const { mouseCoords, cameraHeading, measurementLabel, drawMode } = useMapStore();

  return (
    <footer className="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex items-end justify-between gap-3 p-3 md:p-4">
      <div className="pointer-events-auto ev-panel flex flex-wrap items-center gap-3 px-3 py-2 font-mono text-[11px] text-earth-300">
        <span className="inline-flex items-center gap-1.5">
          <MousePointer2 className="h-3.5 w-3.5 text-orbit-400" />
          {mouseCoords
            ? `${mouseCoords.latitude.toFixed(5)}°, ${mouseCoords.longitude.toFixed(5)}°`
            : '—'}
        </span>
        <span className="h-3 w-px bg-earth-700" />
        <span className="inline-flex items-center gap-1.5">
          <Compass
            className="h-3.5 w-3.5 text-soil-400"
            style={{ transform: `rotate(${-cameraHeading}deg)` }}
          />
          {cameraHeading.toFixed(0)}°
        </span>
        {measurementLabel && (
          <>
            <span className="h-3 w-px bg-earth-700" />
            <span className="inline-flex items-center gap-1.5 text-soil-400">
              <Ruler className="h-3.5 w-3.5" />
              {measurementLabel}
            </span>
          </>
        )}
        {drawMode !== 'none' && (
          <>
            <span className="h-3 w-px bg-earth-700" />
            <span className="text-orbit-400">Draw: {drawMode}</span>
          </>
        )}
      </div>

      <div className="pointer-events-auto ev-panel px-3 py-2">
        <div className="flex items-end gap-2">
          <div className="h-1 w-16 rounded-full bg-earth-100/80" />
          <span className="font-mono text-[10px] text-earth-400">scale</span>
        </div>
      </div>
    </footer>
  );
}
