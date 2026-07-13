"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { LatencyStats } from "../lib/api";

interface Props {
  latency: LatencyStats;
}

const ROWS = [
  { pct: "p50", color: "var(--success)" },
  { pct: "p95", color: "var(--warn)" },
  { pct: "p99", color: "var(--error)" },
] as const;

export default function LatencyCard({ latency }: Props) {
  const reduceMotion = useReducedMotion();
  const rows = ROWS.flatMap(({ pct, color }) => {
    const ms = latency[pct];
    return ms !== null ? [{ pct, ms, color }] : [];
  });
  const max = Math.max(...rows.map((r) => r.ms), 1);

  return (
    <div>
      <h2 className="card-label">Latency (ms)</h2>
      {rows.length === 0 ? (
        <div className="empty-state">
          <span className="status-dot" />
          No completed requests in this window
        </div>
      ) : (
        <div className="latency-rows">
          {rows.map((r, i) => (
            <div className="latency-row" key={r.pct}>
              <span className="latency-row-label">{r.pct}</span>
              <div className="latency-row-track">
                <motion.div
                  className="latency-row-fill"
                  style={{ background: r.color }}
                  initial={{ width: reduceMotion ? `${(r.ms / max) * 100}%` : "0%" }}
                  animate={{ width: `${(r.ms / max) * 100}%` }}
                  transition={{
                    duration: reduceMotion ? 0 : 0.5,
                    delay: reduceMotion ? 0 : i * 0.08,
                    ease: [0.22, 1, 0.36, 1],
                  }}
                />
              </div>
              <span className="latency-row-value">{r.ms.toFixed(0)} ms</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
