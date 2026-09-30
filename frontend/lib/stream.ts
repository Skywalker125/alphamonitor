import { API_URL, type ScanItem } from "./api";

type Handler = (data: any) => void;
type ConnListener = (connected: boolean) => void;

const handlers = new Map<string, Set<Handler>>();
const connListeners = new Set<ConnListener>();
const attached = new Set<string>();
let source: EventSource | null = null;

function attach(name: string) {
  if (!source || attached.has(name)) return;
  attached.add(name);
  source.addEventListener(name, (e) => {
    let data: unknown;
    try {
      data = JSON.parse((e as MessageEvent).data);
    } catch {
      return;
    }
    handlers.get(name)?.forEach((h) => h(data));
  });
}

function ensure() {
  if (source || typeof window === "undefined") return;
  source = new EventSource(`${API_URL}/api/stream`);
  attached.clear();
  source.onopen = () => connListeners.forEach((l) => l(true));
  source.onerror = () => connListeners.forEach((l) => l(false));
  handlers.forEach((_, name) => attach(name));
}

function maybeClose() {
  const any = [...handlers.values()].some((s) => s.size > 0);
  if (source && !any && connListeners.size === 0) {
    source.close();
    source = null;
  }
}

/** Subscribe to one named server-sent event (one shared EventSource for the whole app). */
export function onStreamEvent<T = any>(name: string, h: (data: T) => void) {
  if (!handlers.has(name)) handlers.set(name, new Set());
  handlers.get(name)!.add(h);
  ensure();
  attach(name);
  return () => {
    handlers.get(name)?.delete(h);
    maybeClose();
  };
}

/** Live scan messages pushed by the backend. */
export function onScan(l: (feed: string, item: ScanItem) => void) {
  return onStreamEvent<{ feed: string; item: ScanItem }>("scan", (d) => l(d.feed, d.item));
}

export function onConnection(l: ConnListener) {
  connListeners.add(l);
  ensure();
  return () => {
    connListeners.delete(l);
    maybeClose();
  };
}
