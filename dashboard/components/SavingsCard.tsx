import type { SavingsStats } from "../lib/api";
import CountUp from "./CountUp";

interface Props {
  savings: SavingsStats;
  isFirstLoad?: boolean;
}

export default function SavingsCard({ savings, isFirstLoad = false }: Props) {
  const cents = Number(savings.cost_saved_cents);
  const isZero = cents === 0;
  const inDollars = cents >= 100;
  const displayValue = inDollars ? cents / 100 : cents;

  return (
    <div>
      <h2 className="card-label">Cache savings</h2>
      <div className={`metric-value${isZero ? " is-zero" : ""}`}>
        {inDollars && "$"}
        <CountUp value={displayValue} decimals={4} animate={isFirstLoad} />
        {!inDollars && <span className="metric-accent">¢</span>}
      </div>
      <div className="metric-hint">
        {isZero
          ? "No cache hits yet in this window"
          : "would-be cost avoided by cache"}
      </div>
    </div>
  );
}
