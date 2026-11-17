"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";

type Peaks = { startSeconds: number; windowSeconds: number; durationSeconds: number; peaks: [number, number][] };

export function BoundaryWaveform({ source, frame, fps, side }: {
  source: string; frame: number; fps: number; side: "in" | "out";
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const context = 1;
  const [data, setData] = useState<Peaks | null>(null);
  const [error, setError] = useState("");
  // OUT is inclusive in the edit model: audio stops after that retained frame.
  const frameOffset = side === "out" ? 1 : 0;
  const center = (frame + frameOffset) / fps;
  const start = Math.max(0, center - context);
  const end = center + context;
  useEffect(() => {
    const abort = new AbortController();
    setData(null);
    setError("");
    const query = new URLSearchParams({ source, start: String(start), end: String(end) });
    fetch(`${API_BASE}/api/projects/current/waveform?${query}`, { signal: abort.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail ?? "Waveform unavailable");
        return response.json() as Promise<Peaks>;
      })
      .then(setData)
      .catch((failure) => { if (!abort.signal.aborted) setError(String(failure.message)); });
    return () => abort.abort();
  }, [source, start, end]);
  useEffect(() => {
    const element = canvas.current;
    const ctx = element?.getContext("2d");
    if (!element || !ctx) return;
    ctx.clearRect(0, 0, element.width, element.height);
    if (!data) return;
    const width = element.width;
    const height = element.height;
    const x = (seconds: number) => (seconds - start) / (end - start) * width;
    ctx.fillStyle = "#0c1018";
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff0b";
    ctx.fillRect(side === "in" ? 0 : x(center), 0, side === "in" ? x(center) : width - x(center), height);
    ctx.strokeStyle = "#22d3c5";
    ctx.beginPath();
    data.peaks.forEach(([min, max], index) => {
      const px = x(data.startSeconds + index * data.windowSeconds);
      const amplitude = (value: number) => Math.sign(value) * Math.sqrt(Math.abs(value)) * 44;
      ctx.moveTo(px, 49 - amplitude(max)); ctx.lineTo(px, 49 - amplitude(min));
    });
    ctx.stroke();
    ctx.strokeStyle = "#ff00ce"; ctx.lineWidth = 6;
    ctx.beginPath(); ctx.moveTo(x(center), 0); ctx.lineTo(x(center), 98); ctx.stroke();
    ctx.lineWidth = 1; ctx.fillStyle = "#a6b2c8"; ctx.font = "18px monospace";
    for (let i = 0; i <= 4; i++) {
      const time = start + (end - start) * i / 4;
      ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
      ctx.fillText(`${(time - center).toFixed(1)}s`, x(time), 124);
    }
  }, [data, start, end, center, side]);
  return <div className="boundary-waveform">
    {error ? <small role="status">{error}</small> : !data ? <small role="status">Loading waveform…</small> : null}
    <canvas ref={canvas} width={800} height={132} aria-label={`${side.toUpperCase()} audio waveform. Adjust with frame controls below.`} role="img" />
  </div>;
}
