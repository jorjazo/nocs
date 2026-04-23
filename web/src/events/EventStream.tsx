import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AuthContext } from "@/auth/AuthContext";
import type { ConnectionState, SseEnvelope } from "./connection";

type Listener = (e: SseEnvelope) => void;

interface StreamApi {
  state: ConnectionState;
  subscribe: (topic: string, fn: Listener) => () => void;
  lastEvent: SseEnvelope | null;
}

const StreamContext = createContext<StreamApi>({
  state: "idle",
  subscribe: () => () => {},
  lastEvent: null,
});

// eslint-disable-next-line react-refresh/only-export-components -- hook colocated with EventStreamProvider (Plan H)
export const useEventStream = () => useContext(StreamContext);

interface EventStreamProps {
  topics?: string[];
  factory?: (url: string) => EventSourceLike;
  children: ReactNode;
}

export interface EventSourceLike {
  addEventListener: (type: string, fn: (e: MessageEvent) => void) => void;
  removeEventListener: (type: string, fn: (e: MessageEvent) => void) => void;
  close: () => void;
  onopen?: ((e: Event) => void) | null;
  onerror?: ((e: Event) => void) | null;
  onmessage?: ((e: MessageEvent) => void) | null;
}

const TOPICS_DEFAULT = [
  "mount",
  "camera",
  "filterwheel",
  "focuser",
  "sequence",
  "safety",
  "session",
  "device_connection",
  "system",
  "target",
  "sensor",
  "platesolving",
];

export function EventStreamProvider({
  topics = TOPICS_DEFAULT,
  factory,
  children,
}: EventStreamProps) {
  const { token } = useContext(AuthContext);
  const [state, setState] = useState<ConnectionState>("idle");
  const [lastEvent, setLastEvent] = useState<SseEnvelope | null>(null);
  const listeners = useRef(new Map<string, Set<Listener>>());

  useEffect(() => {
    if (!token) {
      setState("idle");
      return;
    }
    const params = new URLSearchParams();
    params.set("topics", topics.join(","));
    params.set("token", token);
    const url = `/api/events?${params.toString()}`;
    const make = factory ?? ((u: string) => new EventSource(u) as unknown as EventSourceLike);
    setState("connecting");
    const es = make(url);

    const onOpen = () => setState("open");
    const onError = () => setState("error");
    const handlers: { type: string; fn: (e: MessageEvent) => void }[] = [];

    const eventTypes = Array.from(new Set(topics.flatMap(_eventTypesForTopic)));
    for (const t of eventTypes) {
      const fn = (raw: MessageEvent) => {
        try {
          const data = JSON.parse(raw.data) as SseEnvelope;
          setLastEvent(data);
          listeners.current.get(data.topic)?.forEach((l) => l(data));
        } catch {
          // ignore malformed payloads
        }
      };
      es.addEventListener(t, fn);
      handlers.push({ type: t, fn });
    }
    es.onopen = onOpen;
    es.onerror = onError;

    return () => {
      handlers.forEach((h) => es.removeEventListener(h.type, h.fn));
      es.close();
      setState("closed");
    };
  }, [token, topics, factory]);

  const api: StreamApi = useMemo(
    () => ({
      state,
      lastEvent,
      subscribe: (topic, fn) => {
        let s = listeners.current.get(topic);
        if (!s) {
          s = new Set();
          listeners.current.set(topic, s);
        }
        s.add(fn);
        return () => {
          s!.delete(fn);
        };
      },
    }),
    [state, lastEvent],
  );
  return <StreamContext.Provider value={api}>{children}</StreamContext.Provider>;
}

// Listen on the wildcard "message" plus any explicit event names the backend uses.
// The Spring backend sets `event: <type>` on every line, so we hear them by name; we also
// handle the fallback "message" in case a future emitter omits the event field.
function _eventTypesForTopic(_topic: string): string[] {
  void _topic;
  return [
    "message",
    "device_state_changed",
    "connected",
    "disconnected",
    "exposure_started",
    "exposure_finished",
    "image_saved",
    "filter_selected",
    "focuser_moved",
    "sequence_started",
    "sequence_step",
    "sequence_progress",
    "sequence_paused",
    "sequence_resumed",
    "sequence_aborted",
    "sequence_completed",
    "sequence_failed",
    "safety_rule_triggered",
    "safety_rule_cleared",
    "e_stop",
    "e_stop_reset",
    "session_opened",
    "session_closed",
    "solve_started",
    "solved",
    "solve_failed",
    "install_progress",
    "install_succeeded",
    "install_failed",
    "active_target_changed",
    "sensor_reading_received",
  ];
}
