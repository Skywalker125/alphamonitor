"use client";

/**
 * Cross-feed state for the token rows:
 *  - how many feeds currently show an address (row colour: 1 red, 2 yellow, 3+ green)
 *  - price charts for the first two rows of every feed, fetched once per address
 */

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChartPoints } from "./api";
import { onStreamEvent } from "./stream";

const REFRESH_MS = 20_000; // re-announce wanted charts (backend forgets after 90 s)

type Registry = Map<string, { all: string[]; top: string[] }>;

const RegisterContext = createContext<(feed: string, all: string[], top: string[]) => void>(() => {});
const CountContext = createContext<Map<string, number>>(new Map());
const ChartContext = createContext<Map<string, ChartPoints>>(new Map());

export function BoardProvider({ children }: { children: React.ReactNode }) {
  const [registry, setRegistry] = useState<Registry>(new Map());
  const [charts, setCharts] = useState<Map<string, ChartPoints>>(new Map());

  const register = useMemo(
    () => (feed: string, all: string[], top: string[]) =>
      setRegistry((prev) => {
        const cur = prev.get(feed);
        if (cur && cur.all.join() === all.join() && cur.top.join() === top.join()) return prev;
        const next = new Map(prev);
        next.set(feed, { all, top });
        return next;
      }),
    [],
  );

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const { all } of registry.values()) for (const a of new Set(all)) m.set(a, (m.get(a) ?? 0) + 1);
    return m;
  }, [registry]);

  const wanted = useMemo(() => {
    const s = new Set<string>();
    for (const { top } of registry.values()) top.forEach((a) => s.add(a));
    return [...s].sort();
  }, [registry]);
  const wantedKey = wanted.join(",");
  const wantedRef = useRef(wanted);
  wantedRef.current = wanted;

  // announce the chart tokens now and whenever they change; merge what's already cached
  useEffect(() => {
    let alive = true;
    const announce = () => {
      const mints = wantedRef.current;
      if (!mints.length) return;
      api
        .wantCharts(mints)
        .then((res) => {
          if (!alive || !res) return;
          setCharts((prev) => {
            const next = new Map(prev);
            for (const [mint, c] of Object.entries(res.charts)) if (c.points?.length) next.set(mint, c.points);
            return next;
          });
        })
        .catch(() => {});
    };
    announce();
    const id = setInterval(announce, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [wantedKey]);

  useEffect(
    () =>
      onStreamEvent<{ mint: string; points: ChartPoints }>("chart", (c) => {
        if (!c.points?.length) return;
        setCharts((prev) => new Map(prev).set(c.mint, c.points));
      }),
    [],
  );

  return (
    <RegisterContext.Provider value={register}>
      <CountContext.Provider value={counts}>
        <ChartContext.Provider value={charts}>{children}</ChartContext.Provider>
      </CountContext.Provider>
    </RegisterContext.Provider>
  );
}

/** A feed reports every address it holds and the ones in its first two visible rows. */
export function useRegisterFeed(feed: string, all: (string | null | undefined)[], visible: (string | null | undefined)[]) {
  const register = useContext(RegisterContext);
  const allList = all.filter(Boolean) as string[];
  const top = [...new Set(visible.filter(Boolean) as string[])].slice(0, 2);
  const allKey = allList.join(",");
  const topKey = top.join(",");
  useEffect(() => {
    register(feed, allKey ? allKey.split(",") : [], topKey ? topKey.split(",") : []);
  }, [register, feed, allKey, topKey]);
}

export function useFeedCount(address: string | null | undefined) {
  const counts = useContext(CountContext);
  return address ? counts.get(address) ?? 0 : 0;
}

export function presenceClass(count: number) {
  if (count >= 3) return "presence-3";
  if (count === 2) return "presence-2";
  if (count === 1) return "presence-1";
  return "";
}

export function useChart(address: string | null | undefined) {
  const charts = useContext(ChartContext);
  return address ? charts.get(address) : undefined;
}

export const useFeedCounts = () => useContext(CountContext);
export const useCharts = () => useContext(ChartContext);
