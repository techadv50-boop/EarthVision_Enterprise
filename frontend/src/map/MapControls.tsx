import { useEffect, useState } from 'react';
import * as Cesium from 'cesium';
import { useMapStore } from '@/store/mapStore';

function formatScale(meters: number): string {
  if (meters >= 1_000_000) return `${(meters / 1_000_000).toFixed(0)} Mm`;
  if (meters >= 1000) return `${(meters / 1000).toFixed(meters >= 10000 ? 0 : 1)} km`;
  return `${Math.round(meters)} m`;
}

export default function MapControls() {
  const { mousePosition, viewer, setCameraHeight, setHeading, heading, cameraHeight } =
    useMapStore();
  const [scaleLabel, setScaleLabel] = useState('100 km');
  const [scaleWidth, setScaleWidth] = useState(96);

  useEffect(() => {
    if (!viewer) return;

    const update = () => {
      const height = viewer.camera.positionCartographic.height;
      setCameraHeight(height);
      setHeading(Cesium.Math.toDegrees(viewer.camera.heading));

      const canvas = viewer.scene.canvas;
      const center = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
      const left = new Cesium.Cartesian2(center.x - 50, center.y);
      const right = new Cesium.Cartesian2(center.x + 50, center.y);
      const leftPos = viewer.camera.pickEllipsoid(left);
      const rightPos = viewer.camera.pickEllipsoid(right);
      if (leftPos && rightPos) {
        const meters = Cesium.Cartesian3.distance(leftPos, rightPos);
        const nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000];
        let target = nice[0];
        for (const n of nice) {
          if (n <= meters) target = n;
        }
        const px = Math.max(40, Math.min(140, (target / meters) * 100));
        setScaleWidth(px);
        setScaleLabel(formatScale(target));
      }
    };

    viewer.camera.changed.addEventListener(update);
    update();
    return () => {
      viewer.camera.changed.removeEventListener(update);
    };
  }, [viewer, setCameraHeight, setHeading]);

  const formatCoord = (value: number, isLat: boolean) => {
    const abs = Math.abs(value);
    const deg = Math.floor(abs);
    const min = ((abs - deg) * 60).toFixed(3);
    const dir = isLat ? (value >= 0 ? 'N' : 'S') : value >= 0 ? 'E' : 'W';
    return `${deg}°${min}' ${dir}`;
  };

  return (
    <>
      <div className="absolute bottom-4 left-4 panel px-4 py-2 text-xs font-mono z-10">
        <div className="flex gap-4">
          <span>Lon: {formatCoord(mousePosition.longitude, false)}</span>
          <span>Lat: {formatCoord(mousePosition.latitude, true)}</span>
          <span>Cam: {(cameraHeight / 1000).toFixed(1)} km</span>
        </div>
      </div>

      <div className="absolute bottom-4 right-4 panel px-3 py-2 z-10">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-full border-2 border-earth-400 flex items-center justify-center"
            style={{ transform: `rotate(${-heading}deg)` }}
          >
            <div className="w-0 h-0 border-l-[4px] border-r-[4px] border-b-[8px] border-l-transparent border-r-transparent border-b-earth-400" />
          </div>
          <span className="text-xs text-gray-400">N</span>
        </div>
      </div>

      <div className="absolute bottom-16 left-1/2 -translate-x-1/2 panel px-4 py-1 z-10">
        <div className="flex items-center gap-2">
          <div className="h-0.5 bg-white" style={{ width: scaleWidth }} />
          <span className="text-xs text-gray-400">{scaleLabel}</span>
        </div>
      </div>
    </>
  );
}
