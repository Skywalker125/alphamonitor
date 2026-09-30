"use client";

import { fmtDuration, parseTs } from "@/lib/format";
import { useSignalFor } from "@/lib/signals";

/** Live watch status of a token on its feed rows: watching / entry / skipped. */
export default function SignalBadge({ mint, now }: { mint: string | null | undefined; now: number }) {
  const s = useSignalFor(mint);
  if (!s) return null;
  const title = s.reasons?.join("\n") || undefined;
  if (s.status === "WATCHING") {
    const elapsed = (now - (parseTs(s.started_at) ?? now)) / 1000;
    return (
      <span className="badge badge-watch" title={title}>
        👁 {fmtDuration(elapsed)}
        {s.score != null ? ` · ${Math.round(s.score)}` : ""}
      </span>
    );
  }
  if (s.status === "ENTRY") {
    return (
      <span className="badge badge-green" title={title}>
        ✅ ENTRY {Math.round(s.score ?? 0)}
      </span>
    );
  }
  return (
    <span className="badge badge-muted" title={title}>
      ✖ skip {Math.round(s.best_score ?? 0)}
    </span>
  );
}
