"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type CallItem } from "@/lib/api";
import { fmtUsd, gmgnUrl, parseTs, timeAgo } from "@/lib/format";
import { copyAddress, hasTextSelection } from "@/lib/copy";
import FeedColumn, { type Filter } from "./FeedColumn";
import TokenAvatar from "./TokenAvatar";

const POLL_MS = 5000;

const PARAMS = {
  min_calls: "1",
  interval: "1d",
  sort: "recent",
  chain: "solana",
  calls_per_token: "0",
  limit: "25",
  offset: "0",
};

const currentMc = (c: CallItem) =>
  c.chain_candidates?.find((x) => x.chain === c.chain)?.market_cap ?? c.chain_candidates?.[0]?.market_cap ?? null;

const FILTERS: Filter<CallItem>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "caught", label: "Caught", test: (c) => !!c.catch_state && c.catch_state !== "IGNORED" },
  { id: "under100k", label: "MCap < $100K", test: (c) => (currentMc(c) ?? Infinity) < 100_000 },
  { id: "up", label: "Up since call", test: (c) => (currentMc(c) ?? 0) > (c.first_call_market_cap ?? Infinity) },
];

function catchClass(state?: string | null) {
  if (!state || state === "IGNORED") return "badge-muted";
  if (/A_?PLUS|CAUGHT|SIGNAL/i.test(state)) return "badge-green";
  return "badge-amber";
}

export default function CallsFeed({ now }: { now: number }) {
  const [items, setItems] = useState<CallItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const seen = useRef<Set<number> | null>(null);
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  useEffect(() => {
    let alive = true;
    let ctrl: AbortController | null = null;
    const load = async () => {
      ctrl?.abort();
      ctrl = new AbortController();
      try {
        const data = await api.calls(PARAMS, ctrl.signal);
        if (!alive) return;
        const list = data.items ?? [];
        // flash rows that appeared since the previous poll (not on first load)
        if (seen.current) {
          const added = new Set(list.filter((i) => !seen.current!.has(i.id)).map((i) => i.id));
          if (added.size) setFresh(added);
        }
        seen.current = new Set(list.map((i) => i.id));
        setItems(list);
        setError(null);
      } catch (e) {
        if (alive && (e as Error).name !== "AbortError") setError(`Calls API: ${(e as Error).message}`);
      } finally {
        if (alive) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      ctrl?.abort();
      clearInterval(id);
    };
  }, []);

  const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
  const visible = useMemo(() => items.filter(f.test), [items, f]);

  return (
    <FeedColumn
      icon="✈️"
      title="Telegram"
      subtitle="Latest calls from tracked Telegram channels (1d)."
      meta={`${items.length} tokens`}
      filters={FILTERS}
      activeFilter={filter}
      onFilter={setFilter}
      error={error}
      loading={loading}
      emptyText="No calls yet."
      count={visible.length}
    >
      {visible.map((c) => {
        const mc = currentMc(c);
        const firstMc = c.first_call_market_cap;
        const mult = mc && firstMc ? mc / firstMc : null;
        const url = c.pair_url || c.links?.gmgn || gmgnUrl(c.address, c.chain);
        const progress = c.launchpad_progress != null ? Math.round(c.launchpad_progress * 100) : null;
        return (
          <div
            key={c.id}
            className={`row ${fresh.has(c.id) ? "fresh" : ""}`}
            title="Click to copy the token address"
            onClick={(e) => !hasTextSelection(e.currentTarget) && copyAddress(c.address, c.symbol)}
          >
            <TokenAvatar src={c.image_url} symbol={c.symbol} />
            <div className="row-main">
              <div className="row-line">
                <span className="sym">{c.symbol ?? "?"}</span>
                {c.launchpad_platform && (
                  <span className="badge badge-muted" title={c.launchpad_platform}>
                    {c.launchpad_platform}
                    {progress != null && progress < 100 ? ` ${progress}%` : ""}
                  </span>
                )}
                {c.catch_label && (
                  <span className={`badge ${catchClass(c.catch_state)}`} title={c.catch_reason ?? ""}>
                    {c.catch_label}
                  </span>
                )}
                {mult != null && (
                  <span className={`amount ${mult >= 1 ? "pos" : "neg"}`}>{mult.toFixed(2)}x</span>
                )}
              </div>
              <div className="row-line sub">
                <span className="name">{c.name}</span>
                <span className="dim">· called at</span> <b>{fmtUsd(firstMc)}</b>
                <span className="dim">· now</span> <b>{fmtUsd(mc)}</b>
              </div>
            </div>
            <div className="row-side">
              <span className="ago">{timeAgo(parseTs(c.first_call_at), now)}</span>
              <a
                className="chip chip-btn"
                href={url}
                target="_blank"
                rel="noreferrer"
                title="Open chart"
                onClick={(e) => e.stopPropagation()}
              >
                ↗
              </a>
            </div>
          </div>
        );
      })}
    </FeedColumn>
  );
}
