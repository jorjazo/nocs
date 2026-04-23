import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { EventStreamProvider, type EventSourceLike } from "./EventStream";
import { ConnectionPill } from "@/ui/ConnectionPill";
import { AuthProvider } from "@/auth/AuthProvider";
import { setToken, clearToken } from "@/api/token";

class FakeES implements EventSourceLike {
  static last: FakeES | null = null;
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  private listeners = new Map<string, Set<(e: MessageEvent) => void>>();
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeES.last = this;
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    let s = this.listeners.get(type);
    if (!s) {
      s = new Set();
      this.listeners.set(type, s);
    }
    s.add(fn);
  }
  removeEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.get(type)?.delete(fn);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, payload: unknown) {
    const ev = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.forEach((fn) => fn(ev));
  }
  open() {
    this.onopen?.(new Event("open"));
  }
}

describe("EventStreamProvider", () => {
  beforeEach(() => {
    clearToken();
    FakeES.last = null;
  });
  afterEach(() => clearToken());

  it("connects when a token is present and reports open state", () => {
    setToken("dev");
    render(
      <AuthProvider>
        <EventStreamProvider factory={(u) => new FakeES(u)}>
          <ConnectionPill />
        </EventStreamProvider>
      </AuthProvider>,
    );
    expect(FakeES.last?.url).toMatch(/\/api\/events\?topics=.*&token=dev/);
    act(() => FakeES.last!.open());
    expect(screen.getByRole("status")).toHaveTextContent("open");
  });

  it("stays idle without a token", () => {
    render(
      <AuthProvider>
        <EventStreamProvider factory={(u) => new FakeES(u)}>
          <ConnectionPill />
        </EventStreamProvider>
      </AuthProvider>,
    );
    expect(FakeES.last).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("idle");
  });
});
