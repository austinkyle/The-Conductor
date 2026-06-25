import type { CacheStats } from "../lib/api";

interface Props {
  cache: CacheStats;
}

export default function CacheCard({ cache }: Props) {
  const hitRate = (cache.hit_rate * 100).toFixed(1);
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
        Cache
      </h2>
      <div style={{ fontSize: 32, fontWeight: 700, color: "#16a34a" }}>
        {hitRate}%
      </div>
      <div style={{ color: "#888", fontSize: 13, marginBottom: 12 }}>
        hit rate
      </div>
      <table
        style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
      >
        <tbody>
          <tr>
            <td>Exact hits</td>
            <td style={{ textAlign: "right", fontWeight: 600 }}>
              {cache.exact_hit.toLocaleString()}
            </td>
          </tr>
          <tr>
            <td>Semantic hits</td>
            <td style={{ textAlign: "right", fontWeight: 600 }}>
              {cache.semantic_hit.toLocaleString()}
            </td>
          </tr>
          <tr>
            <td>Misses</td>
            <td style={{ textAlign: "right", fontWeight: 600 }}>
              {cache.miss.toLocaleString()}
            </td>
          </tr>
          <tr style={{ borderTop: "1px solid #eee" }}>
            <td style={{ paddingTop: 6 }}>Total</td>
            <td
              style={{
                textAlign: "right",
                fontWeight: 600,
                paddingTop: 6,
              }}
            >
              {cache.total.toLocaleString()}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
