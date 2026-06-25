const BASE =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

export type Window = "24h" | "7d" | "30d";

export type SpendBucket = { ts: string; cost_cents: number };
export type CacheStats = {
  total: number;
  exact_hit: number;
  semantic_hit: number;
  miss: number;
  hit_rate: number;
};
export type LatencyStats = {
  p50: number | null;
  p95: number | null;
  p99: number | null;
};
export type SavingsStats = { cost_saved_cents: number };
export type FailoverEvent = {
  ts: string;
  requested_model: string | null;
  served_model: string | null;
  fallback_depth: number;
};
export type KeyUsage = {
  name: string;
  requests: number;
  total_tokens: number;
  cost_cents: number;
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  spend: (w: Window, bucket = "day") =>
    get<SpendBucket[]>(
      `/v1/observability/spend?window=${w}&bucket=${bucket}`
    ),
  cache: (w: Window) =>
    get<CacheStats>(`/v1/observability/cache?window=${w}`),
  latency: (w: Window) =>
    get<LatencyStats>(`/v1/observability/latency?window=${w}`),
  savings: (w: Window) =>
    get<SavingsStats>(`/v1/observability/savings?window=${w}`),
  failovers: (w: Window) =>
    get<FailoverEvent[]>(`/v1/observability/failovers?window=${w}`),
  keys: (w: Window) =>
    get<KeyUsage[]>(`/v1/observability/keys?window=${w}`),
};
