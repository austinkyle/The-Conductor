import type { SavingsStats } from "../lib/api";

interface Props {
  savings: SavingsStats;
}

export default function SavingsCard({ savings }: Props) {
  const cents = Number(savings.cost_saved_cents);
  const display =
    cents >= 100 ? `$${(cents / 100).toFixed(4)}` : `${cents.toFixed(4)}¢`;

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
        Cache savings
      </h2>
      <div style={{ fontSize: 32, fontWeight: 700, color: "#0070f3" }}>
        {display}
      </div>
      <div style={{ color: "#888", fontSize: 13 }}>
        would-be cost avoided by cache
      </div>
    </div>
  );
}
