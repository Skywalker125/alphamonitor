"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, type WatchSession } from "./api";
import { onStreamEvent } from "./stream";

export type LiveSession = WatchSession & { mcDir?: 1 | -1; mcAt?: number };

type Ctx = {
  enabled: boolean;
  sessions: Map<string, LiveSession>; // latest session per mint
  dismiss: (mint: string) => void;
  sound: boolean;
  setSound: (on: boolean) => void;
};

const SignalsContext = createContext<Ctx>({
  enabled: false,
  sessions: new Map(),
  dismiss: () => {},
  sound: false,
  setSound: () => {},
});

const REFRESH_MS = 30_000;
const SOUND_KEY = "alphamonitor:entry-sound";

function beep() {
  try {
    const ac = new AudioContext();
    const o = ac.createOscillator();
    const g = ac.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(880, ac.currentTime);
    o.frequency.setValueAtTime(1320, ac.currentTime + 0.12);
    g.gain.setValueAtTime(0.15, ac.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.4);
    o.connect(g).connect(ac.destination);
    o.start();
    o.stop(ac.currentTime + 0.4);
  } catch {}
}

function latestPerMint(rows: WatchSession[]) {
  const map = new Map<string, LiveSession>();
  for (const r of rows) {
    const cur = map.get(r.mint);
    if (!cur || r.id > cur.id) map.set(r.mint, r);
  }
  return map;
}

export function SignalsProvider({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabled] = useState(false);
  const [sessions, setSessions] = useState<Map<string, LiveSession>>(new Map());
  const [sound, setSoundState] = useState(false);
  const seenEntries = useRef<Set<number> | null>(null);
  const soundRef = useRef(false);

  useEffect(() => {
    try {
      const on = localStorage.getItem(SOUND_KEY) === "1";
      setSoundState(on);
      soundRef.current = on;
    } catch {}
  }, []);

  const setSound = useCallback((on: boolean) => {
    setSoundState(on);
    soundRef.current = on;
    try {
      localStorage.setItem(SOUND_KEY, on ? "1" : "0");
    } catch {}
    if (on) beep();
  }, []);

  const noteEntries = useCallback((list: Iterable<WatchSession>) => {
    const ids = [...list].filter((s) => s.status === "ENTRY").map((s) => s.id);
    if (!seenEntries.current) {
      seenEntries.current = new Set(ids); // first load: don't beep for old entries
      return;
    }
    const fresh = ids.filter((id) => !seenEntries.current!.has(id));
    fresh.forEach((id) => seenEntries.current!.add(id));
    if (fresh.length && soundRef.current) beep();
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .signals(60)
        .then((d) => {
          if (!alive) return;
          setEnabled(d.enabled);
          const map = latestPerMint(d.sessions);
          noteEntries(map.values());
          setSessions((prev) => {
            // keep a fresher live market cap than the (5 s old) database value
            for (const [mint, s] of map) {
              const p = prev.get(mint);
              if (p && p.id === s.id && p.mcAt && p.last_mc != null) map.set(mint, { ...s, last_mc: p.last_mc, mcAt: p.mcAt });
            }
            return map;
          });
        })
        .catch(() => {});
    load();
    const id = setInterval(load, REFRESH_MS);

    const offWatch = onStreamEvent<Partial<WatchSession> & { mint: string; id: number; dismissed?: boolean }>(
      "watch",
      (ev) => {
        setSessions((prev) => {
          const next = new Map(prev);
          const cur = next.get(ev.mint);
          if (ev.dismissed) {
            if (cur && cur.id === ev.id) next.set(ev.mint, { ...cur, dismissed_at: new Date().toISOString() });
            return next;
          }
          if (cur && cur.id > ev.id) return prev; // stale event for an older session
          const merged = { ...(cur && cur.id === ev.id ? cur : {}), ...ev } as LiveSession;
          if (cur?.mcAt && cur.id === ev.id && cur.last_mc != null) {
            merged.last_mc = cur.last_mc; // live tick is newer than the 5 s evaluation
            merged.mcAt = cur.mcAt;
          }
          next.set(ev.mint, merged);
          if (ev.status === "ENTRY") noteEntries([merged]);
          return next;
        });
      },
    );

    const offMc = onStreamEvent<{ mint: string; mc: number; t: number }>("mc", (ev) => {
      setSessions((prev) => {
        const cur = prev.get(ev.mint);
        if (!cur) return prev;
        const next = new Map(prev);
        const dir = cur.last_mc != null && ev.mc !== cur.last_mc ? (ev.mc > cur.last_mc ? 1 : -1) : cur.mcDir;
        next.set(ev.mint, {
          ...cur,
          last_mc: ev.mc,
          peak_mc: Math.max(cur.peak_mc ?? 0, ev.mc),
          mcDir: dir,
          mcAt: Date.now(),
        });
        return next;
      });
    });

    return () => {
      alive = false;
      clearInterval(id);
      offWatch();
      offMc();
    };
  }, [noteEntries]);

  const dismiss = useCallback((mint: string) => {
    setSessions((prev) => {
      const cur = prev.get(mint);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(mint, { ...cur, dismissed_at: new Date().toISOString() });
      return next;
    });
    api.dismissSignal(mint).catch(() => {});
  }, []);

  const value = useMemo(() => ({ enabled, sessions, dismiss, sound, setSound }), [enabled, sessions, dismiss, sound, setSound]);
  return <SignalsContext.Provider value={value}>{children}</SignalsContext.Provider>;
}

export const useSignals = () => useContext(SignalsContext);

export function useSignalFor(mint: string | null | undefined) {
  const { sessions } = useContext(SignalsContext);
  return mint ? sessions.get(mint) : undefined;
}
