import { API_URL, type ScanItem } from "./api";

type Listener = (feed: string, item: ScanItem) => void;
type ConnListener = (connected: boolean) => void;

const listeners = new Set<Listener>();
const connListeners = new Set<ConnListener>();
let source: EventSource | null = null;

function ensure() {
  if (source || typeof window === "undefined") return;
  source = new EventSource(`${API_URL}/api/stream`);
  source.onopen = () => connListeners.forEach((l) => l(true));
  source.onerror = () => connListeners.forEach((l) => l(false));
  source.addEventListener("scan", (e) => {
    try {
      const { feed, item } = JSON.parse((e as MessageEvent).data);
      listeners.forEach((l) => l(feed, item));
    } catch {}
  });
}

function maybeClose() {
  if (source && listeners.size === 0 && connListeners.size === 0) {
    source.close();
    source = null;
  }
}

/** Subscribe to live scan messages pushed by the backend (one shared EventSource). */
export function onScan(l: Listener) {
  listeners.add(l);
  ensure();
  return () => {
    listeners.delete(l);
    maybeClose();
  };
}

export function onConnection(l: ConnListener) {
  connListeners.add(l);
  ensure();
  return () => {
    connListeners.delete(l);
    maybeClose();
  };
}
