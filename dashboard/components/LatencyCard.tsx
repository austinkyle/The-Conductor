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
  { pct: "p50", color: "#4ade80" },
  { pct: "p95", color: "#fb923c" },
  { pct: "p99", color: "#f87171" },
] as const;

export default function LatencyCard({ latency }: Props) {
  const data = ROWS.flatMap(({ pct, color }) => {
    const ms = latency[pct];
    return ms !== null ? [{ pct, ms, color }] : [];
  });

  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 8,
        border: "1px solid #eee",
        padding: 16,
      }}
    >
      <h2 style={{ margin: "0 0 12px 0", fontSize: 15, fontWeight: 600 }}>
        Latency (ms)
      </h2>
      {data.length === 0 ? (
        <p style={{ color: "#888" }}>No data.</p>
      ) : (
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={data} layout="vertical">
            <XAxis type="number" tick={{ fontSize: 11 }} unit=" ms" />
            <YAxis
              type="category"
              dataKey="pct"
              tick={{ fontSize: 12 }}
              width={28}
            />
            <Tooltip
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
