export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export interface SseEnvelope {
  topic: string;
  type: string;
  ts: string;
  payload?: Record<string, unknown>;
}
