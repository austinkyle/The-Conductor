"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { SpendBucket } from "../lib/api";

interface Props {
  data: SpendBucket[];
}

function fmtDate(ts: string): string {
  return new Date(ts).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export default function SpendChart({ data }: Props) {
  const chartData = data.map((d) => ({
    ts: fmtDate(d.ts),
    cents: Number(d.cost_cents),
  }));

  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 8,
        border: "1px solid #eee",
        padding: "16px 8px",
      }}
    >
      <h2 style={{ margin: "0 0 12px 8px", fontSize: 15, fontWeight: 600 }}>
        Spend over time
      </h2>
      {chartData.length === 0 ? (
        <p style={{ color: "#888", padding: "0 8px" }}>
          No data for this window.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="ts" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} unit="¢" />
            <Tooltip
              formatter={(v) => [`${Number(v ?? 0).toFixed(4)}¢`, "Cost"]}
            />
            <Area
              type="monotone"
              dataKey="cents"
              stroke="#0070f3"
              fill="#e0f0ff"
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
