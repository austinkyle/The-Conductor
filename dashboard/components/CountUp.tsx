"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

interface Props {
  value: number;
  decimals?: number;
  /** Count up from 0 on this render; pass false for silent value updates (refresh). */
  animate?: boolean;
  duration?: number;
}

export default function CountUp({
  value,
  decimals = 0,
  animate = true,
  duration = 600,
}: Props) {
  const reduceMotion = useReducedMotion();
  const shouldAnimate = animate && !reduceMotion;
  const [display, setDisplay] = useState(shouldAnimate ? 0 : value);
  const frame = useRef<number>();

  // Silent updates (auto-refresh) — no animation, just reflect the new value.
  useEffect(() => {
    if (!shouldAnimate) setDisplay(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, shouldAnimate]);

  // One-shot count-up on first load.
  useEffect(() => {
    if (!shouldAnimate) return;
    const start = performance.now();

    function tick(now: number) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(value * eased);
      if (progress < 1) {
        frame.current = requestAnimationFrame(tick);
      } else {
        setDisplay(value);
      }
    }

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldAnimate]);

  const formatted = display.toFixed(decimals);

  return (
    <motion.span
      key={shouldAnimate ? "counting" : formatted}
      className="tabular-nums"
      initial={shouldAnimate || reduceMotion ? false : { opacity: 0.3 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      {formatted}
    </motion.span>
  );
}
