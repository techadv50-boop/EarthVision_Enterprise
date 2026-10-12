import { describe, expect, it } from "vitest";
import { encodeWav, mergeFloat32, resampleLinear } from "./wav";

describe("wav encoding", () => {
  it("writes a mono PCM header and the sample payload", () => {
    const wav = encodeWav(new Float32Array([0, 0.5, -0.5]), 16000);
    expect(String.fromCharCode(...wav.slice(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...wav.slice(8, 12))).toBe("WAVE");
    expect(wav.length).toBe(44 + 6);
    const view = new DataView(wav.buffer);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
  });

  it("resamples and merges captured chunks", () => {
    const merged = mergeFloat32([new Float32Array([0, 1]), new Float32Array([0.5])]);
    expect(Array.from(merged)).toEqual([0, 1, 0.5]);
    const down = resampleLinear(new Float32Array([0, 1, 0, 1]), 4, 2);
    expect(down.length).toBe(2);
  });
});
