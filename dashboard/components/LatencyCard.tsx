"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
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
  const data = ROWS.flatMap(({ pct, color }) => {
    const ms = latency[pct];
    return ms !== null ? [{ pct, ms, color }] : [];
  });

  return (
    <div className="card">
      <h2 className="card-label">Latency (ms)</h2>
      {data.length === 0 ? (
        <div className="empty-state">
          <span className="status-dot" />
          No completed requests in this window
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={data} layout="vertical">
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              unit=" ms"
              stroke="var(--border)"
            />
            <YAxis
              type="category"
              dataKey="pct"
              tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
              width={28}
              stroke="var(--border)"
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 12,
              }}
              itemStyle={{
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
              }}
              labelStyle={{ color: "var(--text-secondary)" }}
              formatter={(v) => [`${Number(v ?? 0).toFixed(0)} ms`, "Latency"]}
            />
            <Bar dataKey="ms" radius={[0, 4, 4, 0]}>
              {data.map((r) => (
                <Cell key={r.pct} fill={r.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
