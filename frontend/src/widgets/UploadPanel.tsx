import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, Upload, Satellite } from 'lucide-react';
import { offlineApi } from '@/services/api';
import { useStackStore } from '@/store/stackStore';
import { useUIStore } from '@/store/uiStore';
import { useMapStore } from '@/store/mapStore';

const DEFAULT_ACCEPT =
  '.tif,.tiff,.geotiff,.cog,.jp2,.j2k,.jpg,.jpeg,.png,.bmp,.webp,.gif,.img,.nc,.hdf,.h5,.hdf5,.asc,.bil,.vrt';

export default function UploadPanel() {
  const [loading, setLoading] = useState(false);
  const [placeName, setPlaceName] = useState('');
  const [acquisitionDate, setAcquisitionDate] = useState('');
  const [acquisitionTime, setAcquisitionTime] = useState('');
  const [longitude, setLongitude] = useState('');
  const [latitude, setLatitude] = useState('');
  const [altitudeM, setAltitudeM] = useState('');
  const [cloudCover, setCloudCover] = useState('');
  const [sensor, setSensor] = useState('');
  const [platform, setPlatform] = useState('');
  const [resolutionM, setResolutionM] = useState('');
  const [notes, setNotes] = useState('');
  const [label, setLabel] = useState('');
  const [showOptional, setShowOptional] = useState(false);
  const [accept, setAccept] = useState(DEFAULT_ACCEPT);
  const [formatsNote, setFormatsNote] = useState('GeoTIFF, JPEG2000, JPG/PNG, HDF/NetCDF, IMG…');
  const [lastResult, setLastResult] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { showNotification } = useUIStore();
  const { loadStacks, setActiveStack } = useStackStore();
  const { addAnalysisLayer, flyTo } = useMapStore();

  useEffect(() => {
    void offlineApi.formats().then(({ data }) => {
      if (data?.accept) setAccept(data.accept);
      if (Array.isArray(data?.extensions)) {
        setFormatsNote(data.extensions.join(', '));
      }
    }).catch(() => {
      /* keep defaults */
    });
  }, []);

  const handleUpload = async (file: File) => {
    if (!placeName.trim()) {
      showNotification('Place name is required to group images of the same location', 'error');
      return;
    }
    if (!acquisitionDate.trim()) {
      showNotification('Acquisition date is compulsory', 'error');
      return;
    }

    setLoading(true);
    setLastResult(null);
    try {
      const { data } = await offlineApi.uploadToStack(file, {
        place_name: placeName.trim(),
        acquisition_date: acquisitionDate,
        acquisition_time: acquisitionTime || undefined,
        longitude: longitude !== '' ? Number(longitude) : undefined,
        latitude: latitude !== '' ? Number(latitude) : undefined,
        altitude_m: altitudeM !== '' ? Number(altitudeM) : undefined,
        cloud_cover: cloudCover !== '' ? Number(cloudCover) : undefined,
        sensor: sensor || undefined,
        platform: platform || undefined,
        resolution_m: resolutionM !== '' ? Number(resolutionM) : undefined,
        notes: notes || undefined,
        label: label || undefined,
      });
      const stack = data.stack;
      const count = stack.image_count ?? data.image_count ?? 0;
      setLastResult(
        `Added “${data.acquisition_date}” to “${stack.name}” — ${count} image(s). ` +
          (data.normalized
            ? `Converted ${data.format || 'file'} → GeoTIFF for GIS tools. `
            : '') +
          (count >= 2
            ? `Date slider max = ${count} (index 0…${count - 1}).`
            : 'Upload more dated images of this place to enable the slider.'),
      );
      await loadStacks();
      setActiveStack(stack);
      const tilePath = data.working_path || data.file_path;
      if (tilePath) {
        const url =
          `/api/v1/raster/tiles/{z}/{x}/{y}.png?file_path=${encodeURIComponent(tilePath)}`;
        addAnalysisLayer(url);
      }
      if (stack.longitude != null && stack.latitude != null) {
        flyTo(stack.longitude, stack.latitude, 250000);
      }
      showNotification('Image uploaded with metadata', 'success');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Upload failed — check format and required date';
      showNotification(String(detail), 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-sateye-mist/60 leading-relaxed">
        Feed SAT EYE offline by uploading imagery from your PC. Acquisition date is required;
        other metadata is optional. Any accepted format is normalized so all 148 GIS tools can run.
      </p>

      <div className="space-y-2">
        <label className="text-xs text-sateye-mist/50 uppercase tracking-wider">
          Place name <span className="text-sateye-teal">*</span>
        </label>
        <input
          className="input-field text-sm"
          placeholder="e.g. Nile Delta, Demo Valley"
          value={placeName}
          onChange={(e) => setPlaceName(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs text-sateye-mist/50 uppercase tracking-wider">
          Acquisition date <span className="text-sateye-teal">* compulsory</span>
        </label>
        <input
          type="date"
          className="input-field text-sm"
          value={acquisitionDate}
          onChange={(e) => setAcquisitionDate(e.target.value)}
          required
        />
      </div>

      <button
        type="button"
        onClick={() => setShowOptional((v) => !v)}
        className="w-full flex items-center justify-between text-xs text-sateye-mist/60 hover:text-sateye-teal py-1"
      >
        <span>Optional metadata (time, location, sensor…)</span>
        {showOptional ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>

      {showOptional && (
        <div className="space-y-3 panel p-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">Time</label>
              <input
                type="time"
                step={1}
                className="input-field text-sm"
                value={acquisitionTime}
                onChange={(e) => setAcquisitionTime(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Cloud cover %
              </label>
              <input
                type="number"
                min={0}
                max={100}
                className="input-field text-sm"
                value={cloudCover}
                onChange={(e) => setCloudCover(e.target.value)}
                placeholder="0–100"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Longitude
              </label>
              <input
                type="number"
                step="any"
                className="input-field text-sm"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
                placeholder="e.g. 31.23"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Latitude
              </label>
              <input
                type="number"
                step="any"
                className="input-field text-sm"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
                placeholder="e.g. 30.04"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Altitude (m)
              </label>
              <input
                type="number"
                step="any"
                className="input-field text-sm"
                value={altitudeM}
                onChange={(e) => setAltitudeM(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Resolution (m)
              </label>
              <input
                type="number"
                step="any"
                className="input-field text-sm"
                value={resolutionM}
                onChange={(e) => setResolutionM(e.target.value)}
                placeholder="e.g. 10"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">Sensor</label>
              <input
                className="input-field text-sm"
                value={sensor}
                onChange={(e) => setSensor(e.target.value)}
                placeholder="e.g. MSI, OLI"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">
                Platform
              </label>
              <input
                className="input-field text-sm"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                placeholder="e.g. Sentinel-2"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">Label</label>
            <input
              className="input-field text-sm"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Display name (optional)"
            />
          </div>

          <div className="space-y-1">
            <label className="text-[10px] uppercase tracking-wider text-sateye-mist/45">Notes</label>
            <textarea
              className="input-field text-sm min-h-[64px]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes"
            />
          </div>
        </div>
      )}

      <label
        className={`btn-primary w-full flex items-center justify-center gap-2 text-sm cursor-pointer ${
          loading || !acquisitionDate || !placeName.trim() ? 'opacity-60 pointer-events-none' : ''
        }`}
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
        Upload Image
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          disabled={loading || !acquisitionDate || !placeName.trim()}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleUpload(file);
            e.target.value = '';
          }}
        />
      </label>

      <div className="panel p-3 text-xs text-sateye-mist/55 space-y-1">
        <div className="flex items-center gap-2 text-sateye-teal">
          <Satellite className="w-3.5 h-3.5" />
          Multi-format offline feed
        </div>
        <p>
          <span className="text-sateye-mist/70">Date *</span> is compulsory. Time, location, sensor,
          cloud cover, and notes are optional.
        </p>
        <p className="break-words">Accepted: {formatsNote}</p>
        <p>Each upload is normalized to GeoTIFF so GIS tools work on every format.</p>
      </div>

      {lastResult && (
        <div className="text-xs text-sateye-teal/90 leading-relaxed">{lastResult}</div>
      )}
    </div>
  );
}
