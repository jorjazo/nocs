import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { EventStreamProvider, type EventSourceLike } from "./EventStream";
import { useTopic } from "./useTopic";
import { AuthProvider } from "@/auth/AuthProvider";
import { setToken, clearToken } from "@/api/token";

let captured: (EventSourceLike & { emit: (t: string, p: unknown) => void }) | null = null;

function makeFake(url: string) {
  const listeners = new Map<string, Set<(e: MessageEvent) => void>>();
  const fake: EventSourceLike & { emit: (t: string, p: unknown) => void } = {
    addEventListener: (t, fn) => {
      let s = listeners.get(t);
      if (!s) {
        s = new Set();
        listeners.set(t, s);
      }
      s.add(fn);
    },
    removeEventListener: (t, fn) => listeners.get(t)?.delete(fn),
    close: () => {},
    onopen: null,
    onerror: null,
    onmessage: null,
    emit: (t, p) =>
      listeners.get(t)?.forEach((fn) => fn(new MessageEvent(t, { data: JSON.stringify(p) }))),
  };
  void url;
  captured = fake;
  return fake;
}

function Probe({ topic }: { topic: string }) {
  const ev = useTopic(topic);
  return <div data-testid="last">{ev?.type ?? "—"}</div>;
}

describe("useTopic", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
    captured = null;
  });
  afterEach(() => clearToken());

  it("captures events for the requested topic", () => {
    render(
      <AuthProvider>
        <EventStreamProvider factory={makeFake}>
          <Probe topic="mount" />
        </EventStreamProvider>
      </AuthProvider>,
    );
    act(() =>
      captured!.emit("device_state_changed", {
        topic: "mount",
        type: "device_state_changed",
        ts: "2026-04-23T00:00:00Z",
      }),
    );
    expect(screen.getByTestId("last")).toHaveTextContent("device_state_changed");
  });
});
