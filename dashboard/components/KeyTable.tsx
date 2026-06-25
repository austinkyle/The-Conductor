import type { KeyUsage } from "../lib/api";

interface Props {
  keys: KeyUsage[];
}

export default function KeyTable({ keys }: Props) {
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
        Per-key usage
      </h2>
      {keys.length === 0 ? (
        <p style={{ color: "#888" }}>
          No authenticated requests in this window.
        </p>
      ) : (
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
        >
          <thead>
            <tr
              style={{ borderBottom: "1px solid #eee", textAlign: "left" }}
            >
              <th style={{ padding: "4px 8px", fontWeight: 600 }}>Key</th>
              <th
                style={{
                  padding: "4px 8px",
                  fontWeight: 600,
                  textAlign: "right",
                }}
              >
                Requests
              </th>
              <th
                style={{
                  padding: "4px 8px",
                  fontWeight: 600,
                  textAlign: "right",
                }}
              >
                Tokens
              </th>
              <th
                style={{
                  padding: "4px 8px",
                  fontWeight: 600,
                  textAlign: "right",
                }}
              >
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.name} style={{ borderBottom: "1px solid #f5f5f5" }}>
                <td
                  style={{ padding: "4px 8px", fontFamily: "monospace" }}
                >
                  {k.name}
                </td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>
                  {k.requests.toLocaleString()}
                </td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>
                  {k.total_tokens.toLocaleString()}
                </td>
                <td style={{ padding: "4px 8px", textAlign: "right" }}>
                  {Number(k.cost_cents).toFixed(4)}¢
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
