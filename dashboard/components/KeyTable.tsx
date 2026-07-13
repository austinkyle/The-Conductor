"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { KeyUsage } from "../lib/api";

interface Props {
  keys: KeyUsage[];
}

function CopyableKey({ name }: { name: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(name);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="copy-key focus-ring"
      title="Copy key name"
    >
      {name}
      <AnimatePresence>
        {copied && (
          <motion.span
            className="copy-tick"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            copied
          </motion.span>
        )}
      </AnimatePresence>
    </button>
  );
}

export default function KeyTable({ keys }: Props) {
  return (
    <div>
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
                <td className="mono">
                  <CopyableKey name={k.name} />
                </td>
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
