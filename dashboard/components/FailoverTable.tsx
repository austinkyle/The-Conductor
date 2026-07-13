import type { FailoverEvent } from "../lib/api";

interface Props {
  failovers: FailoverEvent[];
}

export default function FailoverTable({ failovers }: Props) {
  return (
    <div>
      <h2 className="card-label">Failover events</h2>
      {failovers.length === 0 ? (
        <div className="empty-state">
          <span className="status-dot" style={{ color: "var(--success)" }} />
          No failovers in this window
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Requested</th>
              <th>Served</th>
              <th className="num">Depth</th>
            </tr>
          </thead>
          <tbody>
            {failovers.map((f, i) => (
              <tr key={i}>
                <td style={{ color: "var(--text-secondary)" }}>
                  {new Date(f.ts).toLocaleString()}
                </td>
                <td className="mono">{f.requested_model ?? "—"}</td>
                <td className="mono">{f.served_model ?? "—"}</td>
                <td className="num">{f.fallback_depth}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
