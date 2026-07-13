"use client";

import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  index?: number;
  style?: React.CSSProperties;
  className?: string;
}

const EASE = [0.22, 1, 0.36, 1] as const;

export default function MotionCard({ children, index = 0, style, className }: Props) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className={`card motion-card${className ? ` ${className}` : ""}`}
      style={style}
      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduceMotion ? 0.2 : 0.45,
        delay: reduceMotion ? 0 : index * 0.07,
        ease: EASE,
      }}
      whileHover={
        reduceMotion
          ? undefined
          : { y: -1, borderColor: "var(--border-hover)", transition: { duration: 0.15 } }
      }
    >
      {children}
    </motion.div>
  );
}
