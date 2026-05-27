import { motion } from "framer-motion";
import { useEffect, useRef } from "react";

import type { Quiz } from "../../api/types";

const ROUND_LABELS: Record<Quiz["rounds"][number]["type"], string> = {
  meta_strategy: "META STRATEGY",
  list_race: "LIST RACE",
  buzz_in: "BUZZ-IN",
  sync_open: "OPEN ANSWER",
};

const ROUND_SUBTITLES: Record<Quiz["rounds"][number]["type"], string> = {
  meta_strategy: "BET ON YOURSELF",
  list_race: "NAME THEM ALL",
  buzz_in: "FIRST TO ANSWER",
  sync_open: "TYPE TO WIN",
};

export function RoundIntroSlate({
  roundNumber,
  roundType,
  onComplete,
  holdMs = 2500,
}: {
  roundNumber: number;
  roundType: Quiz["rounds"][number]["type"];
  onComplete: () => void;
  holdMs?: number;
}) {
  const onCompleteRef = useRef(onComplete);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    const timer = window.setTimeout(() => onCompleteRef.current(), holdMs);
    return () => window.clearTimeout(timer);
  }, [holdMs]);

  return (
    <motion.div
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-midnight"
      exit={{ opacity: 0 }}
      initial={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
    >
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-stagegold/10 via-transparent to-transparent" />
        <div className="relative text-center text-white">
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="text-xs font-semibold uppercase tracking-[0.4em] text-stagegold"
            initial={{ opacity: 0, y: 12 }}
            transition={{ delay: 0.1, duration: 0.3 }}
          >
            Round
          </motion.div>
          <motion.div
            animate={{ scale: 1, opacity: 1 }}
            className="mt-3 font-display text-[clamp(5rem,18vw,14rem)] leading-none tabular-nums"
            initial={{ scale: 1.2, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 20, delay: 0.05 }}
          >
            {roundNumber}
          </motion.div>
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="mt-6 inline-flex items-center gap-3 rounded-full border border-white/15 bg-white/5 px-5 py-2 text-sm font-bold uppercase tracking-[0.4em] text-white/85"
            initial={{ opacity: 0, y: 12 }}
            transition={{ delay: 0.3, duration: 0.3 }}
          >
            <span className="h-2 w-2 rounded-full bg-magenta" />
            {ROUND_LABELS[roundType]}
            <span className="h-2 w-2 rounded-full bg-magenta" />
          </motion.div>
          <motion.div
            animate={{ opacity: 1 }}
            className="mt-6 text-xs font-semibold uppercase tracking-[0.5em] text-white/55"
            initial={{ opacity: 0 }}
            transition={{ delay: 0.55, duration: 0.4 }}
          >
            {ROUND_SUBTITLES[roundType]}
          </motion.div>
      </div>
    </motion.div>
  );
}
