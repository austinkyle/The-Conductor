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
    <div style={{ display: "flex", gap: 4 }}>
      {OPTIONS.map((w) => (
        <button
          key={w}
          onClick={() => onChange(w)}
          style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: "1px solid",
            borderColor: value === w ? "#0070f3" : "#ddd",
            background: value === w ? "#0070f3" : "#fff",
            color: value === w ? "#fff" : "#333",
            cursor: "pointer",
            fontWeight: value === w ? 600 : 400,
            fontSize: 13,
          }}
        >
          {LABELS[w]}
        </button>
      ))}
    </div>
  );
}
