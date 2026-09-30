"use client";

import { useEffect, useState } from "react";
import CallsFeed from "@/components/CallsFeed";
import ScanFeed from "@/components/ScanFeed";
import Toast from "@/components/Toast";
import { api, type FeedMeta, type ListenerStatus } from "@/lib/api";
import { useNow } from "@/lib/format";
import { onConnection } from "@/lib/stream";

export default function Home() {
  const now = useNow(1000);
  const [feeds, setFeeds] = useState<FeedMeta[] | null>(null);
  const [feedsError, setFeedsError] = useState<string | null>(null);
  const [status, setStatus] = useState<ListenerStatus | null>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    api.feeds().then(setFeeds).catch((e) => setFeedsError((e as Error).message));
    const loadStatus = () => api.status().then((s) => setStatus(s.telegram)).catch(() => setStatus(null));
    loadStatus();
    const id = setInterval(loadStatus, 15000);
    const off = onConnection(setLive);
    return () => {
      clearInterval(id);
      off();
    };
  }, []);

  const scanFeeds = (feeds ?? []).filter((f) => f.kind === "scan");

  return (
    <div className="app">
      <nav className="topbar">
        <span className="logo">
          ALPHA<span>MONITOR</span>
        </span>
        <span className="nav-item active">Feeds</span>
        <div className="spacer" />
        {status && (
          <span className={`listener listener-${status.state}`} title={status.error ?? ""}>
            TG listener: {status.state}
          </span>
        )}
      </nav>
      <div className="page-head">
        <h1>Feeds</h1>
        <span className={`live ${live ? "on" : ""}`}>● {live ? "LIVE" : "OFFLINE"}</span>
        {status?.error && <span className="head-error">{status.error}</span>}
      </div>
      {feedsError ? (
        <div className="notice notice-error">Backend unreachable: {feedsError}</div>
      ) : (
        <main className="columns">
          <CallsFeed now={now} />
          {scanFeeds.map((f) => (
            <ScanFeed key={f.key} feed={f} now={now} />
          ))}
        </main>
      )}
      <Toast />
    </div>
  );
}
