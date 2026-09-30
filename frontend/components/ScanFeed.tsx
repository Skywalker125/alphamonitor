"use client";

import { useEffect, useMemo, useState } from "react";
import { api, scanKey, type FeedMeta, type ScanItem } from "@/lib/api";
import { fmtNum, fmtUsd, gmgnUrl, timeAgo, telegramMsgUrl } from "@/lib/format";
import { onScan } from "@/lib/stream";
import { copyAddress, hasTextSelection } from "@/lib/copy";
import FeedColumn, { type Filter } from "./FeedColumn";
import TokenAvatar from "./TokenAvatar";

const MAX_ITEMS = 200;

const SOCIAL_ICONS: Record<string, string> = {
  web: "🌐",
  x: "𝕏",
  telegram: "✈️",
  discord: "💬",
  tiktok: "🎵",
  youtube: "▶️",
  instagram: "📷",
  other: "🔗",
};

const FILTERS: Filter<ScanItem>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "audit7", label: "Audit ≥ 7", test: (s) => (s.parsed.audit_score ?? 0) >= 7 },
  { id: "under1m", label: "MCap < $1M", test: (s) => (s.market_cap ?? Infinity) < 1_000_000 },
  { id: "lowbundle", label: "Bundled < 30%", test: (s) => (s.parsed.bundled_pct ?? 100) < 30 },
  { id: "dexpaid", label: "DEX paid", test: (s) => s.parsed.dex_paid === true },
  { id: "socials", label: "Has socials", test: (s) => (s.parsed.socials?.length ?? 0) > 0 },
];

function auditClass(score?: number, max = 10) {
  if (score == null) return "badge-muted";
  const r = score / max;
  if (r >= 0.7) return "badge-green";
  if (r >= 0.5) return "badge-amber";
  return "badge-red";
}

function pctClass(v: number | undefined, warn: number, bad: number) {
  if (v == null) return "";
  if (v >= bad) return "neg";
  if (v >= warn) return "warn";
  return "pos";
}

function dexImage(address: string | null, chain?: string | null) {
  if (!address) return null;
  return `https://dd.dexscreener.com/ds-data/tokens/${chain === "evm" ? "ethereum" : "solana"}/${address}.png`;
}

function ScanRow({ s, now, fresh }: { s: ScanItem; now: number; fresh: boolean }) {
  const [open, setOpen] = useState(false);
  const p = s.parsed;
  const trigger = s.reply
    ? [s.reply.sender_name, s.reply.text.split("\n").find((l) => l.trim())].filter(Boolean).join(": ")
    : null;
  const urlButtons = s.buttons.filter((b) => b.url);
  const socials = p.socials ?? [];

  return (
    <div
      className={`row scan ${fresh ? "fresh" : ""}`}
      title={s.address ? "Click to copy the token address" : undefined}
      onClick={() => s.address && !hasTextSelection() && copyAddress(s.address, s.symbol)}
    >
      <TokenAvatar src={dexImage(s.address, p.chain)} symbol={s.symbol} />
      <div className="row-main">
        <div className="row-line">
          <span className="sym">{s.symbol ?? "?"}</span>
          {p.audit_score != null && (
            <span className={`badge ${auditClass(p.audit_score, p.audit_max)}`}>
              Audit {p.audit_score}/{p.audit_max ?? 10}
            </span>
          )}
          {p.age && <span className="badge badge-muted">🌱 {p.age}</span>}
          <span className="amount">{fmtUsd(s.market_cap)}</span>
        </div>
        <div className="row-line sub">
          <span className="name">{s.name}</span>
          {trigger ? (
            <span className="dim ellipsis">· {trigger}</span>
          ) : p.first_caller ? (
            <span className="dim ellipsis">
              · first call {p.first_caller} @ {fmtUsd(p.first_call_mc)}
            </span>
          ) : null}
        </div>
        <div className="stats">
          <span>LIQ <b>{fmtUsd(p.liquidity)}</b></span>
          <span>VOL <b>{fmtUsd(p.volume)}</b></span>
          <span>HLD <b>{fmtNum(p.holders)}</b></span>
          {p.buys_1h != null && (
            <span>
              1H <b className="pos">{p.buys_1h}</b>/<b className="neg">{p.sells_1h}</b>
            </span>
          )}
          {p.top10_pct != null && <span>T10 <b className={pctClass(p.top10_pct, 20, 35)}>{p.top10_pct}%</b></span>}
          {p.bundled_pct != null && <span>BNDL <b className={pctClass(p.bundled_pct, 20, 40)}>{p.bundled_pct}%</b></span>}
          {p.sniped_pct != null && <span>SNP <b className={pctClass(p.sniped_pct, 10, 25)}>{p.sniped_pct}%</b></span>}
          {p.dex_paid != null && <span className={p.dex_paid ? "pos" : "dim"}>{p.dex_paid ? "DEX paid" : "DEX unpaid"}</span>}
        </div>
        {socials.length > 0 && (
          <div className="socials">
            {socials.map((so) => (
              <a
                key={so.url}
                className={`social social-${so.kind}`}
                href={so.url}
                target="_blank"
                rel="noreferrer"
                title={so.url}
                onClick={(e) => e.stopPropagation()}
              >
                <span className="social-icon">{SOCIAL_ICONS[so.kind] ?? "🔗"}</span>
                {so.kind === "x" ? null : so.label}
              </a>
            ))}
          </div>
        )}
        {open && (
          <div className="expand" onClick={(e) => e.stopPropagation()}>
            <div className="links">
              {s.address && (
                <a href={gmgnUrl(s.address)} target="_blank" rel="noreferrer">GMGN</a>
              )}
              {s.address && (
                <a href={`https://dexscreener.com/solana/${s.address}`} target="_blank" rel="noreferrer">DexScreener</a>
              )}
              <a href={telegramMsgUrl(s.chat_id, s.message_id, s.chat_username)} target="_blank" rel="noreferrer">
                Telegram msg
              </a>
              {urlButtons.map((b, i) => (
                <a key={i} href={b.url!} target="_blank" rel="noreferrer">{b.text}</a>
              ))}
            </div>
            <pre className="raw">{s.raw_text}</pre>
          </div>
        )}
      </div>
      <div className="row-side">
        <span className="ago" title={new Date(s.posted_at).toLocaleString()}>
          {timeAgo(Date.parse(s.posted_at), now)}
        </span>
        <button
          className={`chip chip-btn ${open ? "active" : ""}`}
          title={open ? "Hide message" : "Show full message and links"}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((o) => !o);
          }}
        >
          {open ? "▴" : "▾"}
        </button>
        {s.chat_title && <span className="chat" title={s.chat_title}>{s.chat_title}</span>}
      </div>
    </div>
  );
}

export default function ScanFeed({ feed, now }: { feed: FeedMeta; now: number }) {
  const [items, setItems] = useState<ScanItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    api
      .scans(feed.key)
      .then((d) => alive && (setItems(d.items), setError(null)))
      .catch((e) => alive && setError((e as Error).message))
      .finally(() => alive && setLoading(false));

    const off = onScan((key, item) => {
      if (key !== feed.key) return;
      const k = scanKey(item);
      setItems((prev) => {
        const idx = prev.findIndex((p) => scanKey(p) === k);
        if (idx >= 0) {
          // edited message (TokenScan refreshes its stats in place)
          const next = prev.slice();
          next[idx] = item;
          return next;
        }
        return [item, ...prev].slice(0, MAX_ITEMS);
      });
      setFresh(new Set([k]));
    });
    return () => {
      alive = false;
      off();
    };
  }, [feed.key]);

  const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
  const visible = useMemo(() => items.filter(f.test), [items, f]);

  return (
    <FeedColumn
      icon="📡"
      title={feed.title}
      subtitle={feed.description || "TokenScan messages"}
      meta={`${feed.chats ?? 0} chats`}
      filters={FILTERS}
      activeFilter={filter}
      onFilter={setFilter}
      error={error}
      loading={loading}
      emptyText={feed.chats ? "Waiting for TokenScan messages…" : "No chats configured for this feed."}
      count={visible.length}
    >
      {visible.map((s) => (
        <ScanRow key={scanKey(s)} s={s} now={now} fresh={fresh.has(scanKey(s))} />
      ))}
    </FeedColumn>
  );
}
