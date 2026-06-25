"use client";

import { useEffect, useState } from "react";
import {
  api,
  type Window,
  type SpendBucket,
  type CacheStats,
  type LatencyStats,
  type SavingsStats,
  type FailoverEvent,
  type KeyUsage,
} from "../lib/api";
import WindowSelect from "../components/WindowSelect";
import SpendChart from "../components/SpendChart";
import CacheCard from "../components/CacheCard";
import LatencyCard from "../components/LatencyCard";
import SavingsCard from "../components/SavingsCard";
import FailoverTable from "../components/FailoverTable";
import KeyTable from "../components/KeyTable";

interface DashboardData {
  spend: SpendBucket[];
  cache: CacheStats;
  latency: LatencyStats;
  savings: SavingsStats;
  failovers: FailoverEvent[];
  keys: KeyUsage[];
}

export default function Home() {
  const [period, setPeriod] = useState<Window>("7d");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.spend(period),
      api.cache(period),
      api.latency(period),
      api.savings(period),
      api.failovers(period),
      api.keys(period),
    ])
      .then(([spend, cache, latency, savings, failovers, keys]) => {
        setData({ spend, cache, latency, savings, failovers, keys });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load data");
      })
      .finally(() => setLoading(false));
  }, [period]);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 24,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>
          LLM Gateway
        </h1>
        <WindowSelect value={period} onChange={setPeriod} />
      </div>

      {error && (
        <div
          style={{
            background: "#fee",
            border: "1px solid #fcc",
            borderRadius: 6,
            padding: 12,
            marginBottom: 16,
            color: "#c00",
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}

      {loading && <p style={{ color: "#888" }}>Loading…</p>}

      {data && (
        <div
          style={{
            display: "grid",
            gap: 16,
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          }}
        >
          <div style={{ gridColumn: "1 / -1" }}>
            <SpendChart data={data.spend} />
          </div>
          <SavingsCard savings={data.savings} />
          <CacheCard cache={data.cache} />
          <LatencyCard latency={data.latency} />
          <div style={{ gridColumn: "1 / -1" }}>
            <KeyTable keys={data.keys} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <FailoverTable failovers={data.failovers} />
          </div>
        </div>
      )}
    </main>
  );
}
