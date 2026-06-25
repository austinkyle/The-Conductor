import type { FailoverEvent } from "../lib/api";

interface Props {
  failovers: FailoverEvent[];
}

export default function FailoverTable({ failovers }: Props) {
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
        Failover events
      </h2>
      {failovers.length === 0 ? (
        <p style={{ color: "#888" }}>No failovers in this window.</p>
      ) : (
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
        >
          <thead>
            <tr
              style={{ borderBottom: "1px solid #eee", textAlign: "left" }}
            >
              <th style={{ padding: "4px 8px", fontWeight: 600 }}>Time</th>
              <th style={{ padding: "4px 8px", fontWeight: 600 }}>
                Requested
              </th>
              <th style={{ padding: "4px 8px", fontWeight: 600 }}>Served</th>
              <th style={{ padding: "4px 8px", fontWeight: 600 }}>Depth</th>
            </tr>
          </thead>
          <tbody>
            {failovers.map((f, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f5f5f5" }}>
                <td style={{ padding: "4px 8px", color: "#888" }}>
                  {new Date(f.ts).toLocaleString()}
                </td>
                <td style={{ padding: "4px 8px" }}>
                  {f.requested_model ?? "—"}
                </td>
                <td style={{ padding: "4px 8px" }}>
                  {f.served_model ?? "—"}
                </td>
                <td style={{ padding: "4px 8px" }}>{f.fallback_depth}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
