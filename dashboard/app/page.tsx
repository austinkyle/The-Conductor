"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
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
import MotionCard from "../components/MotionCard";

// If the deployed dashboard bakes a token in at build time, skip the input.
const HAS_BUILD_TIME_TOKEN = Boolean(
  process.env.NEXT_PUBLIC_DASHBOARD_AUTH_TOKEN
);

const REFRESH_INTERVAL_MS = 30_000;

interface DashboardData {
  spend: SpendBucket[];
  cache: CacheStats;
  latency: LatencyStats;
  savings: SavingsStats;
  failovers: FailoverEvent[];
  keys: KeyUsage[];
}

export default function Home() {
  const reduceMotion = useReducedMotion();
  const [period, setPeriod] = useState<Window>("7d");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenVersion, setTokenVersion] = useState(0);
  const [authorized, setAuthorized] = useState(false);
  const [live, setLive] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isFirstLoad, setIsFirstLoad] = useState(true);
  const isFirstLoadRef = useRef(true);

  const load = useCallback(() => {
    setError(null);
    const wasFirstLoad = isFirstLoadRef.current;
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
        setIsFirstLoad(wasFirstLoad);
        setLive(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load data");
        setLive(false);
      })
      .finally(() => {
        setLoading(false);
        isFirstLoadRef.current = false;
      });
  }, [period]);

  // Initial + period/token-change load. Count-up animates only on the very
  // first successful load of the page — re-counting on every period switch
  // or refresh would be noise, not signal.
  useEffect(() => {
    setLoading(true);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, tokenVersion]);

  // 30s auto-refresh, restarting whenever a manual reload happens.
  useEffect(() => {
    const id = setInterval(() => {
      load();
      setRefreshKey((k) => k + 1);
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 24px" }}>
      <div className="refresh-sweep-track">
        <motion.div
          key={refreshKey}
          className="refresh-sweep-fill"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{
            duration: reduceMotion ? 0 : REFRESH_INTERVAL_MS / 1000,
            ease: "linear",
          }}
        />
      </div>

      <div className="topbar">
        <div className="wordmark-group">
          <h1 className="wordmark">The Conductor</h1>
          <span className="live-dot-wrap">
            <span className={`live-dot ${live ? "is-live" : "is-down"}`} />
            {live ? "Live" : "Unreachable"}
          </span>
        </div>
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
          <MotionCard index={0} style={{ gridColumn: "1 / -1" }}>
            <SpendChart data={data.spend} />
          </MotionCard>
          <MotionCard index={1}>
            <SavingsCard savings={data.savings} isFirstLoad={isFirstLoad} />
          </MotionCard>
          <MotionCard index={2}>
            <CacheCard cache={data.cache} isFirstLoad={isFirstLoad} />
          </MotionCard>
          <MotionCard index={3}>
            <LatencyCard latency={data.latency} />
          </MotionCard>
          <MotionCard index={4} style={{ gridColumn: "1 / -1" }}>
            <KeyTable keys={data.keys} />
          </MotionCard>
          <MotionCard index={5} style={{ gridColumn: "1 / -1" }}>
            <FailoverTable failovers={data.failovers} />
          </MotionCard>
        </div>
      )}
    </main>
  );
}
