// Handing this device's pairing over to the box's new name (ADR 0044). The pairing
// cookie belongs to the host name the browser used, and the old <name>.local stops
// answering once the box is renamed: the page gets a one-time token first, waits for
// the new name, and opens the same screen there with the token in the URL's fragment,
// which no request, server log or Referer carries. The new page redeems it at once.

// After the route in the fragment: #/rig?handoff=<token>. The router ignores it.
export const HANDOFF_PARAM = "handoff";

// How long to wait for the new name to answer, and how often to try.
export const WAIT_MS = 60_000;
export const RETRY_MS = 2_000;

function normalize(name: string): string {
  return name.trim().toLowerCase().replace(/\.$/, "");
}

// Whether the page was reached by the box's mDNS name, `name`.local, which renaming
// ends; not by an address or another name, which keep working.
export function reachedByName(hostname: string, name: string): boolean {
  return normalize(name) !== "" && normalize(hostname) === `${normalize(name)}.local`;
}

// The box under its new name, with this page's scheme and port.
export function originFor(name: string, page: { protocol: string; port: string }): string {
  return `${page.protocol}//${normalize(name)}.local${page.port ? `:${page.port}` : ""}`;
}

// The same screen at `origin`, with the token after the route.
export function handoffUrl(origin: string, hash: string, token: string): string {
  const route = hash.replace(/\?.*$/, "") || "#/";
  return `${origin}/${route.startsWith("#") ? route : `#${route}`}?${HANDOFF_PARAM}=${encodeURIComponent(token)}`;
}

// The handoff token in a fragment, if any, and the fragment without it (other
// parameters, if any, stay).
export function takeHandoff(hash: string): { token: string | null; hash: string } {
  const at = hash.indexOf("?");
  if (at < 0) return { token: null, hash };
  const params = new URLSearchParams(hash.slice(at + 1));
  const token = params.get(HANDOFF_PARAM);
  if (token === null) return { token: null, hash };
  params.delete(HANDOFF_PARAM);
  const rest = params.toString();
  return { token: token || null, hash: hash.slice(0, at) + (rest ? `?${rest}` : "") };
}

export type WaitOptions = {
  timeoutMs?: number;
  intervalMs?: number;
  signal?: AbortSignal;
  // For tests: the fetch, clock and pause to use.
  fetch?: (url: string, init: RequestInit) => Promise<unknown>;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

// Whether `origin` answers within the time allowed. Another origin: an opaque
// response (no-cors) is enough, since it means the name resolves and nocsd answers.
export async function waitUntilAnswers(origin: string, options: WaitOptions = {}): Promise<boolean> {
  const {
    timeoutMs = WAIT_MS,
    intervalMs = RETRY_MS,
    signal,
    fetch: get = (url, init) => fetch(url, init),
    now = Date.now,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = options;
  const deadline = now() + timeoutMs;
  while (!signal?.aborted) {
    try {
      const attempt = AbortSignal.timeout(Math.max(500, Math.min(intervalMs * 2, deadline - now())));
      await get(`${origin}/api/health`, {
        mode: "no-cors",
        cache: "no-store",
        signal: signal ? AbortSignal.any([signal, attempt]) : attempt,
      });
      return !signal?.aborted;
    } catch {
      // not there yet
    }
    if (now() + intervalMs >= deadline) return false;
    await sleep(intervalMs);
  }
  return false;
}
