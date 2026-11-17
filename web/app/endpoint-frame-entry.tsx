"use client";
import { useEffect, useState } from "react";

export function EndpointFrameEntry({ frame, onSet, onPlayhead, onReset }: {
  frame: number; onSet: (frame: number) => void; onPlayhead: () => void; onReset?: () => void;
}) {
  const [draft, setDraft] = useState(String(frame));
  useEffect(() => setDraft(String(frame)), [frame]);
  const valid = draft.trim() !== "" && Number.isInteger(Number(draft)) && Number(draft) >= 0;
  return <div className="final-cut-actions">
    <label>Exact frame <input type="number" min={0} step={1} value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => { if (event.key === "Enter" && valid) onSet(Number(draft)); }} /></label>
    <button disabled={!valid || Number(draft) === frame} onClick={() => onSet(Number(draft))}>Set frame</button>
    <button onClick={onPlayhead}>Set from playhead</button>
    {onReset && <button onClick={onReset}>Reset to transcript</button>}
  </div>;
}
