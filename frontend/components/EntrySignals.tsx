"use client";

import { useMemo } from "react";
import type { FeedMeta, SignalsStatus } from "@/lib/api";
import { copyAddress, hasTextSelection } from "@/lib/copy";
import { fmtDuration, fmtUsd, parseTs, pctChange, timeAgo, tokenImage, useNow } from "@/lib/format";
import { type LiveSession, useSignals } from "@/lib/signals";
import TokenAvatar from "./TokenAvatar";

const ENTRY_WINDOW_MS = 60 * 60 * 1000; // entry cards stay for an hour (live for the first 10 min)

function scoreClass(score: number | null) {
  if (score == null) return "badge-muted";
  if (score >= 70) return "badge-green";
  if (score >= 45) return "badge-amber";
  return "badge-red";
}

function Pct({ value }: { value: number | null }) {
  if (value == null) return <span className="dim">—</span>;
  return <span className={value >= 0 ? "pos" : "neg"}>{`${value >= 0 ? "+" : ""}${value.toFixed(1)}%`}</span>;
}

function EntryCard({ s, now, feedTitle, onDismiss }: {
  s: LiveSession;
  now: number;
  feedTitle: (k: string) => string;
  onDismiss: () => void;
}) {
  const since = pctChange(s.last_mc, s.entry_mc);
  const peak = pctChange(s.peak_mc, s.entry_mc);
  const flash = s.mcAt && now - s.mcAt < 900 ? (s.mcDir === 1 ? "up" : "down") : "";
  return (
    <div
      className={`entry-card ${s.tracking ? "" : "ended"}`}
      title="Click to copy the address"
      onClick={(e) => !hasTextSelection(e.currentTarget) && copyAddress(s.mint, s.symbol)}
    >
      <button
        className="entry-dismiss"
        title="Dismiss"
        onClick={(e) => {
          e.stopPropagation();
          onDismiss();
        }}
      >
        ×
      </button>
      <div className="entry-top">
        <TokenAvatar src={tokenImage(s.mint)} symbol={s.symbol} size={34} />
        <div className="entry-id">
          <div className="entry-sym">
            {s.symbol ?? "?"} <span className={`badge ${scoreClass(s.score)}`}>{Math.round(s.score ?? 0)}</span>
          </div>
          <div className="entry-name">{s.name}</div>
        </div>
        <div className="entry-mc">
          <div className={`entry-mc-value ${flash}`}>{fmtUsd(s.last_mc)}</div>
          <div className="entry-mc-sub">
            {s.tracking ? <span className="live-dot">● live</span> : <span className="dim">final</span>}
          </div>
        </div>
      </div>
      <div className="entry-stats">
        <span>Entry <b>{fmtUsd(s.entry_mc)}</b></span>
        <span>Now <b><Pct value={since} /></b></span>
        <span>Peak <b><Pct value={peak} /></b></span>
        <span className="dim">{timeAgo(parseTs(s.decided_at), now)} ago</span>
      </div>
      <div className="entry-reasons">
        {s.reasons.slice(0, 3).map((r) => (
          <span key={r} className="reason">{r}</span>
        ))}
      </div>
      <div className="entry-sources dim">{s.sources.map(feedTitle).join(" · ")}</div>
    </div>
  );
}

export default function EntrySignals({ feeds, status }: { feeds: FeedMeta[]; status?: SignalsStatus }) {
  const { enabled, sessions, dismiss, sound, setSound } = useSignals();
  const now = useNow(500);
  const titles = useMemo(() => new Map(feeds.map((f) => [f.key, f.title])), [feeds]);
  const feedTitle = (k: string) => titles.get(k) ?? k;

  const all = [...sessions.values()];
  const entries = all
    .filter((s) => s.status === "ENTRY" && !s.dismissed_at && now - (parseTs(s.decided_at) ?? 0) < ENTRY_WINDOW_MS)
    .sort((a, b) => (parseTs(b.decided_at) ?? 0) - (parseTs(a.decided_at) ?? 0));
  const watching = all
    .filter((s) => s.status === "WATCHING")
    .sort((a, b) => (parseTs(a.started_at) ?? 0) - (parseTs(b.started_at) ?? 0));
  const skipped = all
    .filter((s) => s.status === "SKIPPED")
    .sort((a, b) => (parseTs(b.decided_at) ?? 0) - (parseTs(a.decided_at) ?? 0))
    .slice(0, 8);

  if (!enabled) return null;
  const stream = status?.stream;

  return (
    <section className="signals">
      <div className="signals-head">
        <span className="signals-title">🎯 Entry signals</span>
        <span className="dim">
          watching {watching.length}
          {status?.queued ? ` · ${status.queued} queued` : ""}
        </span>
        {stream && !stream.connected && (
          <span className="head-error">Trade stream offline{stream.error ? `: ${stream.error}` : ""}</span>
        )}
        {stream?.connected && <span className="dim">· stream {stream.events_per_s}/s</span>}
        <div className="spacer" />
        <button className={`chip chip-btn ${sound ? "active" : ""}`} onClick={() => setSound(!sound)}>
          {sound ? "🔔 sound on" : "🔕 sound off"}
        </button>
      </div>

      <div className="signals-body">
        <div className="entries">
          {entries.length === 0 ? (
            <div className="entries-empty dim">
              No entry yet. New TokenScan tokens are watched for up to 3 min and appear here when they qualify.
            </div>
          ) : (
            entries.map((s) => (
              <EntryCard key={s.id} s={s} now={now} feedTitle={feedTitle} onDismiss={() => dismiss(s.mint)} />
            ))
          )}
        </div>

        <div className="watch-side">
          {watching.map((s) => {
            const elapsed = (now - (parseTs(s.started_at) ?? now)) / 1000;
            const max = s.max_seconds ?? 180;
            return (
              <div
                key={s.id}
                className="watch-chip"
                title={s.reasons.join("\n") || "Collecting trades…"}
                onClick={() => copyAddress(s.mint, s.symbol)}
              >
                <span className="sym-sm">{s.symbol ?? "?"}</span>
                <span className="watch-bar">
                  <span style={{ width: `${Math.min(100, (elapsed / max) * 100)}%` }} />
                </span>
                <span className="dim">{fmtDuration(elapsed)}</span>
                <span className={`badge ${scoreClass(s.score)}`}>{s.score == null ? "…" : Math.round(s.score)}</span>
              </div>
            );
          })}
          {skipped.map((s) => (
            <div
              key={s.id}
              className="watch-chip skipped"
              title={s.reasons.join("\n")}
              onClick={() => copyAddress(s.mint, s.symbol)}
            >
              <span className="sym-sm">{s.symbol ?? "?"}</span>
              <span className="dim">skip · best {Math.round(s.best_score ?? 0)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
