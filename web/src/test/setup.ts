import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

/** jsdom has no EventSource; EventStreamProvider uses it when a token is set (e.g. App.test). */
if (typeof globalThis.EventSource === "undefined") {
  class EventSourceStub {
    onopen: ((e: Event) => void) | null = null;
    onerror: ((e: Event) => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    constructor(public url: string) {}
    addEventListener() {}
    removeEventListener() {}
    close() {}
  }
  vi.stubGlobal("EventSource", EventSourceStub);
}
