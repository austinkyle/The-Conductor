"use client";

import { useEffect, useState } from "react";
import {
  api,
  setAuthToken,
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

// If the deployed dashboard bakes a token in at build time, skip the input.
const HAS_BUILD_TIME_TOKEN = Boolean(
  process.env.NEXT_PUBLIC_DASHBOARD_AUTH_TOKEN
);

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
  const [tokenInput, setTokenInput] = useState("");
  const [tokenVersion, setTokenVersion] = useState(0);
  const [authorized, setAuthorized] = useState(false);

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
  }, [period, tokenVersion]);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 24px" }}>
      <div className="topbar">
        <h1 className="wordmark">The Conductor</h1>
        <WindowSelect value={period} onChange={setPeriod} />
      </div>

      {!HAS_BUILD_TIME_TOKEN && (
        <div className="token-input-wrap">
          <input
            type="password"
            placeholder="Gateway token (Authorization: Bearer …)"
            value={tokenInput}
            onChange={(e) => {
              setTokenInput(e.target.value);
              setAuthorized(false);
            }}
            className="token-input focus-ring"
          />
          <button
            onClick={() => {
              setAuthToken(tokenInput);
              setAuthorized(tokenInput.length > 0);
              setTokenVersion((v) => v + 1);
            }}
            className="token-apply-btn focus-ring"
          >
            Apply
          </button>
          {authorized && (
            <span className="token-status">
              <span className="status-dot" />
              Authorized
            </span>
          )}
        </div>
      )}

      {error && (
        <div
          style={{
            background: "var(--error-soft)",
            border: "1px solid var(--error)",
            borderRadius: 8,
            padding: 12,
            marginBottom: 24,
            color: "var(--error)",
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}

      {loading && (
        <p style={{ color: "var(--text-secondary)" }}>Loading…</p>
      )}

      {data && (
        <div
          style={{
            display: "grid",
            gap: 24,
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
