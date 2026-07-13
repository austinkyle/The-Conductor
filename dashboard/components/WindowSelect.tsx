"use client";

import type { Window } from "../lib/api";

interface Props {
  value: Window;
  onChange: (w: Window) => void;
}

const OPTIONS: Window[] = ["24h", "7d", "30d"];
const LABELS: Record<Window, string> = {
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
};

export default function WindowSelect({ value, onChange }: Props) {
  return (
    <div className="segmented">
      {OPTIONS.map((w) => (
        <button
          key={w}
          onClick={() => onChange(w)}
          data-active={value === w}
          className="segmented-btn focus-ring"
        >
          {LABELS[w]}
        </button>
      ))}
    </div>
  );
}
