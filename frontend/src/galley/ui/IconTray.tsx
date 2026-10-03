import { useRef, useState } from "react";
import type { IconAsset } from "../types";
import { readIconFile } from "../storage";

export function IconTray({
  label,
  icons,
  maxHeight,
  onChange,
}: {
  label: string;
  icons: IconAsset[];
  maxHeight: number;
  onChange: (icons: IconAsset[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  return (
    <fieldset className="icon-tray">
      <legend>
        {label}
        <button type="button" className="plus" onClick={() => inputRef.current?.click()}>
          +
        </button>
      </legend>
      <input
        ref={inputRef}
        className="hidden-file"
        type="file"
        accept="image/png,image/jpeg,image/gif"
        aria-label={`Upload ${label}`}
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          const icon = await readIconFile(file, maxHeight);
          onChange([...icons, icon]);
        }}
      />
      <div className="icon-row">
        {icons.map((icon, index) => (
          <div
            key={icon.id}
            className="icon-chip"
            draggable
            onDragStart={() => setDragFrom(index)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (dragFrom === null || dragFrom === index) return;
              const next = icons.slice();
              const [moved] = next.splice(dragFrom, 1);
              next.splice(index, 0, moved);
              onChange(next);
              setDragFrom(null);
            }}
          >
            <button
              type="button"
              className="icon-cross"
              aria-label={`Remove ${icon.name}`}
              onClick={() => onChange(icons.filter((item) => item.id !== icon.id))}
            >
              ×
            </button>
            <img src={icon.dataUrl} alt={icon.name} />
          </div>
        ))}
        {icons.length === 0 && <p className="muted">No icons yet. Use + to upload.</p>}
      </div>
    </fieldset>
  );
}
