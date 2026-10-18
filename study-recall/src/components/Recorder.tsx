import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { api, errorText } from "../api";
import { formatClock } from "../format";
import { bytesToBase64, encodeWav, mergeFloat32, resampleLinear } from "../wav";
import { Notice, PrimaryButton, QuietButton } from "./ui";

export type RecorderHandle = {
  stop: () => Promise<Uint8Array | null>;
};

type Props = {
  language: string;
  showTranscribe?: boolean;
  onTranscript?: (text: string, warning: string) => void;
};

type Capture = {
  context: AudioContext;
  stream: MediaStream;
  processor: ScriptProcessorNode;
  mute: GainNode;
  source: MediaStreamAudioSourceNode;
};

export const Recorder = forwardRef<RecorderHandle, Props>(function Recorder({ language, onTranscript, showTranscribe = true }, ref) {
  const [phase, setPhase] = useState<"idle" | "recording" | "paused">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [message, setMessage] = useState("");
  const [warning, setWarning] = useState("");
  const [busy, setBusy] = useState(false);
  const [hasAudio, setHasAudio] = useState(false);
  const chunks = useRef<Float32Array[]>([]);
  const heard = useRef(false);
  const pendingWav = useRef<Uint8Array | null>(null);
  const rate = useRef(48000);
  const capture = useRef<Capture | null>(null);
  const paused = useRef(false);
  const started = useRef(0);
  const pausedTotal = useRef(0);
  const pauseBegan = useRef(0);

  function release() {
    const current = capture.current;
    capture.current = null;
    if (!current) return;
    current.processor.onaudioprocess = null;
    current.source.disconnect();
    current.processor.disconnect();
    current.mute.disconnect();
    current.stream.getTracks().forEach((track) => track.stop());
    void current.context.close();
  }

  function takeWav(): Uint8Array | null {
    const samples = mergeFloat32(chunks.current);
    chunks.current = [];
    if (samples.length === 0) return null;
    const speech = resampleLinear(samples, rate.current, 16000);
    return encodeWav(speech, 16000);
  }

  async function stopCapture(): Promise<Uint8Array | null> {
    paused.current = false;
    release();
    setPhase("idle");
    const wav = takeWav();
    if (wav) {
      pendingWav.current = wav;
      setHasAudio(true);
    }
    return wav;
  }

  async function consumeWav(): Promise<Uint8Array | null> {
    const wav = capture.current ? await stopCapture() : pendingWav.current;
    pendingWav.current = null;
    if (!capture.current) setHasAudio(false);
    return wav;
  }

  useImperativeHandle(ref, () => ({ stop: consumeWav }));

  useEffect(() => () => release(), []);

  useEffect(() => {
    if (phase !== "recording") return;
    const id = window.setInterval(() => {
      setElapsed(performance.now() - started.current - pausedTotal.current);
    }, 200);
    return () => window.clearInterval(id);
  }, [phase]);

  async function record() {
    setMessage("");
    setWarning("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const context = new AudioContext();
      rate.current = context.sampleRate;
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const mute = context.createGain();
      mute.gain.value = 0;
      processor.onaudioprocess = (event) => {
        if (paused.current) return;
        chunks.current.push(new Float32Array(event.inputBuffer.getChannelData(0)));
        if (!heard.current) {
          heard.current = true;
          setHasAudio(true);
        }
      };
      source.connect(processor);
      processor.connect(mute);
      mute.connect(context.destination);
      capture.current = { context, stream, processor, mute, source };
      chunks.current = [];
      heard.current = false;
      pendingWav.current = null;
      paused.current = false;
      started.current = performance.now();
      pausedTotal.current = 0;
      setElapsed(0);
      setPhase("recording");
    } catch {
      setMessage("Microphone permission was denied or no microphone is available. You can type the text instead.");
    }
  }

  function pause() {
    if (phase !== "recording") return;
    paused.current = true;
    pauseBegan.current = performance.now();
    setPhase("paused");
  }

  function resume() {
    if (phase !== "paused") return;
    pausedTotal.current += performance.now() - pauseBegan.current;
    paused.current = false;
    setPhase("recording");
  }

  async function transcribe() {
    const wav = await consumeWav();
    if (!wav) {
      setMessage("Record something first, or type the text.");
      return;
    }
    setBusy(true);
    setMessage("Transcribing on this computer…");
    try {
      const outcome = await api.transcribe(bytesToBase64(wav), language || "auto");
      if (!outcome.ok) {
        setMessage(outcome.errorMessage || "Transcription did not produce text.");
        setWarning("");
        return;
      }
      setMessage(outcome.method === "whisper.cpp" ? "Transcript ready. Correct it before saving." : "Transcript ready.");
      setWarning(outcome.warning);
      onTranscript?.(outcome.text, outcome.warning);
    } catch (err) {
      setMessage(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const status =
    phase === "recording" ? `Recording ${formatClock(elapsed)}` : phase === "paused" ? `Paused ${formatClock(elapsed)}` : "Microphone idle";

  return (
    <section className="rounded-2xl border border-line bg-paper p-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-medium">{status}</p>
        <div className="flex flex-wrap gap-2">
          {phase === "idle" ? <PrimaryButton onClick={() => void record()}>Record voice</PrimaryButton> : null}
          {phase === "recording" ? <QuietButton onClick={pause}>Pause</QuietButton> : null}
          {phase === "paused" ? <QuietButton onClick={resume}>Resume</QuietButton> : null}
          {phase !== "idle" ? (
            <QuietButton
              onClick={() => {
                void stopCapture();
              }}
            >
              Stop recording
            </QuietButton>
          ) : null}
          {showTranscribe ? (
            <QuietButton disabled={busy || (!hasAudio && phase === "idle")} onClick={() => void transcribe()}>
              {busy ? "Transcribing…" : "Transcribe voice"}
            </QuietButton>
          ) : null}
        </div>
      </div>
      <p className="mt-2 text-sm text-muted">
        Speech recognition is included with Study Recall and runs on this computer. Audio is discarded after transcription unless you turn on “Keep recordings” in Settings.
      </p>
      {message ? (
        <div className="mt-3">
          <Notice tone={message.includes("denied") || message.includes("not") || message.includes("unavailable") ? "warn" : "info"}>
            {message}
          </Notice>
        </div>
      ) : null}
      {warning ? (
        <div className="mt-3">
          <Notice tone="warn">{warning}</Notice>
        </div>
      ) : null}
    </section>
  );
});
