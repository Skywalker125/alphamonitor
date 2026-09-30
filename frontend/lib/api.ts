export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001").replace(/\/$/, "");

export type FeedMeta = {
  key: string;
  kind: "calls" | "scan";
  title: string;
  description: string;
  chats?: number;
};

/** One item of the upstream /api/feed/calls response (only the fields we use are typed). */
export type CallItem = {
  id: number;
  address: string;
  chain: string;
  symbol: string | null;
  name: string | null;
  image_url: string | null;
  links?: Record<string, string>;
  pair_url?: string | null;
  launchpad_platform?: string | null;
  launchpad_progress?: number | null;
  chain_candidates?: { chain: string; liquidity_usd?: number; volume_24h?: number; market_cap?: number }[];
  first_call_at: string | null;
  first_call_market_cap: number | null;
  catch_state?: string | null;
  catch_label?: string | null;
  catch_reason?: string | null;
  [k: string]: unknown;
};

export type ScanParsed = {
  name?: string;
  symbol?: string;
  age?: string;
  views?: number;
  market_cap?: number | null;
  ath?: number | null;
  ath_drawdown_pct?: number | null;
  price_usd?: number | null;
  price_change_pct?: number | null;
  liquidity?: number | null;
  volume?: number | null;
  volume_period?: string | null;
  buys_1h?: number;
  sells_1h?: number;
  change_1h_pct?: number | null;
  holders?: number | null;
  audit_score?: number;
  audit_max?: number;
  dex_paid?: boolean;
  top10_pct?: number;
  bundled_pct?: number;
  sniped_pct?: number;
  first_caller?: string;
  first_call_mc?: number | null;
  address?: string | null;
  chain?: string | null;
  socials?: { label: string; url: string; kind: string }[];
};

export type ScanItem = {
  feed_key: string;
  chat_id: number;
  message_id: number;
  chat_title: string | null;
  chat_username: string | null;
  sender_name: string | null;
  posted_at: string;
  edited_at: string | null;
  raw_text: string;
  address: string | null;
  symbol: string | null;
  name: string | null;
  market_cap: number | null;
  parsed: ScanParsed;
  links: { text: string; url: string; offset?: number }[];
  buttons: { text: string; url: string | null }[];
  reply: { message_id: number; sender_name: string | null; text: string } | null;
};

export type ListenerStatus = {
  state: string;
  error: string | null;
  chats: Record<string, { ok: boolean; id?: number; title?: string; error?: string }>;
};

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
  if (!r.ok) {
    let detail = `${r.status}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  feeds: () => getJson<FeedMeta[]>("/api/feeds"),
  status: () => getJson<{ telegram: ListenerStatus }>("/api/status"),
  calls: (params: Record<string, string>, signal?: AbortSignal) =>
    getJson<{ items: CallItem[] }>(`/api/feeds/telegram?${new URLSearchParams(params)}`, signal),
  scans: (feed: string, limit = 100) =>
    getJson<{ items: ScanItem[] }>(`/api/feeds/${encodeURIComponent(feed)}/messages?limit=${limit}`),
};

export const scanKey = (s: Pick<ScanItem, "chat_id" | "message_id">) => `${s.chat_id}:${s.message_id}`;
