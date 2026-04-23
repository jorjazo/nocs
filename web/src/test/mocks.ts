import { vi } from "vitest";

export interface MockResponse {
  status?: number;
  body?: unknown;
  text?: string;
  blob?: Blob;
}

export type Route = string | RegExp | ((url: string, init: RequestInit) => boolean);

export interface RouteHandler {
  match: Route;
  respond:
    | MockResponse
    | ((url: string, init: RequestInit) => MockResponse | Promise<MockResponse>);
}

export function installFetchMock(routes: RouteHandler[]) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    for (const r of routes) {
      const ok =
        typeof r.match === "function"
          ? r.match(url, init)
          : r.match instanceof RegExp
            ? r.match.test(url)
            : url.endsWith(r.match);
      if (ok) {
        const out = typeof r.respond === "function" ? await r.respond(url, init) : r.respond;
        const status = out.status ?? 200;
        if (status === 204) {
          return new Response(null, { status: 204 });
        }
        const body = out.text !== undefined ? out.text : JSON.stringify(out.body ?? null);
        if (out.blob) {
          return new Response(out.blob, { status });
        }
        return new Response(body, {
          status,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(`unhandled ${url}`, { status: 599 });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function uninstallFetchMock() {
  vi.unstubAllGlobals();
}
