import { useEffect, useState } from "react";

export function fmtUsd(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const units: [number, string][] = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [v, s] of units) {
    if (abs >= v) return `$${+(n / v).toFixed(abs / v >= 100 ? 0 : digits)}${s}`;
  }
  return `$${abs >= 1 ? n.toFixed(0) : n.toPrecision(2)}`;
}

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US");
}

/** Upstream timestamps come without timezone ("2026-09-30 00:22:33.68") — treat them as UTC. */
export function parseTs(ts: string | null | undefined): number | null {
  if (!ts) return null;
  let s = ts.trim().replace(" ", "T");
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

export function timeAgo(ts: number | null, now: number): string {
  if (ts == null) return "";
  const s = Math.max(0, Math.floor((now - ts) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export function shortAddr(a: string | null | undefined): string {
  if (!a) return "";
  return a.length > 12 ? `${a.slice(0, 4)}…${a.slice(-4)}` : a;
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function gmgnUrl(address: string, chain = "solana") {
  const c = chain === "solana" ? "sol" : chain;
  return `https://gmgn.ai/${c}/token/${address}`;
}

export function telegramMsgUrl(chatId: number, messageId: number, username?: string | null) {
  if (username) return `https://t.me/${username}/${messageId}`;
  const internal = String(Math.abs(chatId)).replace(/^100/, "");
  return `https://t.me/c/${internal}/${messageId}`;
}
