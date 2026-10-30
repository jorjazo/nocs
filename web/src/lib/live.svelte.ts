// Live mirror of the server state: one WebSocket, a snapshot, then patches.
// Reconnects with backoff and resumes from the last version it holds.

import type { AppState, Json, PatchOp, ServerMessage } from "./types";

// "revoked": the server closed the socket because this device was unpaired
// (or observer access was switched off); reconnecting would not help.
export type LinkStatus = "idle" | "connecting" | "open" | "closed" | "revoked";

// Close code the server uses when the client's access ends (ADR 0014).
export const CLOSE_REVOKED = 4401;

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
  status: LinkStatus = $state("idle");
  // A snapshot has arrived since start(): the state is worth showing.
  synced = $state(false);
  // Socket closes without ever opening, in a row: the handshake is refused or
  // the server is unreachable. The app asks /api/auth what is going on.
  failures = $state(0);
  version = 0;
  #epoch: string | null = null;
  #socket: WebSocket | null = null;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #attempt = 0;
  #running = false;

  // The state tree, typed as the server documents it.
  get app(): AppState {
    return this.state as AppState;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#connect();
  }

  // Stop reconnecting, e.g. once this device is no longer allowed in.
  stop(status: LinkStatus = "idle"): void {
    this.#running = false;
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
    this.status = status;
    this.failures = 0;
  }

  // Reconnect now instead of waiting for the backoff, e.g. when the page
  // becomes visible again after the phone slept.
  wake(): void {
    if (!this.#running || this.status === "open" || this.status === "connecting") return;
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#attempt = 0;
    this.#connect();
  }

  #connect(): void {
    this.#timer = null;
    const url = new URL("/api/ws", location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.#socket = socket;
    this.status = "connecting";
    let opened = false;

    socket.onopen = () => {
      opened = true;
      this.#attempt = 0;
      this.failures = 0;
      this.status = "open";
      socket.send(JSON.stringify({ type: "hello", epoch: this.#epoch, since: this.version }));
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      this.#handle(JSON.parse(event.data) as ServerMessage);
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.#socket !== socket) return; // replaced or stopped
      this.#socket = null;
      if (event.code === CLOSE_REVOKED) {
        this.stop("revoked");
        return;
      }
      this.status = "closed";
      if (!opened) this.failures += 1;
      if (!this.#running) return;
      const delay = BACKOFF_MS[Math.min(this.#attempt, BACKOFF_MS.length - 1)];
      this.#attempt += 1;
      this.#timer = setTimeout(() => this.#connect(), delay);
    };
  }

  #handle(message: ServerMessage): void {
    if (message.type === "snapshot") {
      this.state = message.state;
      this.#epoch = message.epoch;
      this.synced = true;
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
