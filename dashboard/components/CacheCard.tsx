import type { CacheStats } from "../lib/api";

interface Props {
  cache: CacheStats;
}

const ROWS: Array<[label: string, key: keyof CacheStats]> = [
  ["Exact hits", "exact_hit"],
  ["Semantic hits", "semantic_hit"],
  ["Misses", "miss"],
  ["Bypass — no cache", "no_cache"],
  ["Bypass — recent context", "recent_context"],
  ["Bypass — temperature", "temperature"],
  ["Bypass — tool use", "tool_use"],
];

export default function CacheCard({ cache }: Props) {
  const isZero = cache.total === 0;
  const hitRate = (cache.hit_rate * 100).toFixed(1);

  return (
    <div className="card">
      <h2 className="card-label">Cache</h2>
      <div className={`metric-value${isZero ? " is-zero" : ""}`}>
        {hitRate}
        <span className="metric-accent">%</span>
      </div>
      <div className="metric-hint" style={{ marginBottom: isZero ? 0 : 16 }}>
        {isZero ? "No requests in this window" : "hit rate"}
      </div>
      {!isZero && (
        <table className="data-table">
          <tbody>
            {ROWS.map(([label, key]) => (
              <tr key={key}>
                <td style={{ color: "var(--text-secondary)" }}>{label}</td>
                <td className="num">{cache[key].toLocaleString()}</td>
              </tr>
            ))}
            <tr>
              <td style={{ color: "var(--text-secondary)" }}>Total</td>
              <td className="num">{cache.total.toLocaleString()}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
