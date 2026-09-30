/** Copy text to the clipboard. Falls back to execCommand where the Clipboard API is
 *  unavailable (e.g. the app opened over plain http on a LAN IP instead of localhost). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {}
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export const TOAST_EVENT = "alphamonitor:toast";

export function toast(message: string) {
  window.dispatchEvent(new CustomEvent(TOAST_EVENT, { detail: message }));
}

/** Copy a token address and confirm it with a toast. */
export async function copyAddress(address: string, symbol?: string | null) {
  const ok = await copyText(address);
  const short = `${address.slice(0, 4)}…${address.slice(-4)}`;
  toast(ok ? `Copied ${symbol ? `$${symbol} ` : ""}${short}` : "Copy failed - clipboard blocked");
  return ok;
}

/** True when the click ended a drag-select inside `within`, so selecting text doesn't copy.
 *  A selection elsewhere on the page never blocks the click. */
export function hasTextSelection(within?: Element | null) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.toString().length === 0) return false;
  return !within || within.contains(sel.anchorNode);
}
