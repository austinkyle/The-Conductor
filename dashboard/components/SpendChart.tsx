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
    <div>
      <h2 className="card-label">Spend over time</h2>
      {chartData.length === 0 ? (
        <div className="empty-state">
          <span className="status-dot" />
          No spend recorded in this window
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="spendFill" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor="var(--accent)"
                  stopOpacity={0.3}
                />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border)"
              vertical={false}
            />
            <XAxis
              dataKey="ts"
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              stroke="var(--border)"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              unit="¢"
              stroke="var(--border)"
            />
            <Tooltip
              cursor={{ stroke: "var(--accent)", strokeDasharray: "3 3" }}
              contentStyle={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              itemStyle={{
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
              }}
              labelStyle={{ color: "var(--text-secondary)" }}
              formatter={(v) => [`${Number(v ?? 0).toFixed(4)}¢`, "Cost"]}
            />
            <Area
              type="monotone"
              dataKey="cents"
              stroke="var(--accent)"
              fill="url(#spendFill)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
