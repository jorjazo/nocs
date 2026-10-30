// Live mirror of the server state: one WebSocket, a snapshot, then patches.
// Reconnects with backoff and resumes from the last version it holds.

import type { Json, PatchOp, ServerMessage } from "./types";

export type LinkStatus = "connecting" | "open" | "closed";

const BACKOFF_MS = [500, 1000, 2000, 5000];

type JsonObject = { [key: string]: Json };

function isObject(value: Json | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function applyOp(root: JsonObject, op: PatchOp): void {
  const parents = op.path.slice(0, -1);
  const last = op.path.at(-1);
  if (last === undefined) return;
  let node = root;
  for (const key of parents) {
    let child = node[key];
    if (!isObject(child)) {
      if (op.op === "delete") return;
      child = {};
      node[key] = child;
    }
    node = child;
  }
  if (op.op === "set") node[last] = op.value ?? null;
  else delete node[last];
}

class Live {
  state: JsonObject = $state({});
  status: LinkStatus = $state("connecting");
  version = 0;
  #epoch: string | null = null;
  #socket: WebSocket | null = null;
  #attempt = 0;
  #running = false;

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#connect();
  }

  // Stop reconnecting, e.g. once this device is no longer allowed in.
  stop(): void {
    this.#running = false;
    this.#socket?.close();
    this.status = "closed";
  }

  #connect(): void {
    const url = new URL("/api/ws", location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.#socket = socket;
    this.status = "connecting";

    socket.onopen = () => {
      this.#attempt = 0;
      this.status = "open";
      socket.send(JSON.stringify({ type: "hello", epoch: this.#epoch, since: this.version }));
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      this.#handle(JSON.parse(event.data) as ServerMessage);
    };
    socket.onclose = () => {
      this.status = "closed";
      if (!this.#running) return;
      const delay = BACKOFF_MS[Math.min(this.#attempt, BACKOFF_MS.length - 1)];
      this.#attempt += 1;
      setTimeout(() => this.#connect(), delay);
    };
  }

  #handle(message: ServerMessage): void {
    if (message.type === "snapshot") {
      this.state = message.state;
      this.#epoch = message.epoch;
    } else {
      if (message.version !== this.version + 1) {
        // A gap means we missed something; reconnecting asks for it again.
        this.#socket?.close();
        return;
      }
      for (const op of message.ops) applyOp(this.state, op);
    }
    this.version = message.version;
  }
}

export const live = new Live();
