import type { KeyUsage } from "../lib/api";

interface Props {
  keys: KeyUsage[];
}

export default function KeyTable({ keys }: Props) {
  return (
    <div className="card">
      <h2 className="card-label">Per-key usage</h2>
      {keys.length === 0 ? (
        <div className="empty-state">
          <span className="status-dot" />
          No authenticated requests in this window
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Key</th>
              <th className="num">Requests</th>
              <th className="num">Tokens</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.name}>
                <td className="mono">{k.name}</td>
                <td className="num mono">{k.requests.toLocaleString()}</td>
                <td className="num mono">{k.total_tokens.toLocaleString()}</td>
                <td className="num mono">{Number(k.cost_cents).toFixed(4)}¢</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
