import type { SavingsStats } from "../lib/api";

interface Props {
  savings: SavingsStats;
}

export default function SavingsCard({ savings }: Props) {
  const cents = Number(savings.cost_saved_cents);
  const isZero = cents === 0;
  const display =
    cents >= 100 ? `$${(cents / 100).toFixed(4)}` : `${cents.toFixed(4)}¢`;

  return (
    <div className="card">
      <h2 className="card-label">Cache savings</h2>
      <div className={`metric-value${isZero ? " is-zero" : ""}`}>
        {display}
      </div>
      <div className="metric-hint">
        {isZero
          ? "No cache hits yet in this window"
          : "would-be cost avoided by cache"}
      </div>
    </div>
  );
}
