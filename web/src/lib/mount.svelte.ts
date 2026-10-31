// The mount's client side: coordinates as people type and read them, and the
// slew pad's link, whose messages are the server's dead man's switch (ADR 0015).

import type { Messages } from "./i18n";
import type { MountState, PadRequest, PadStatusMessage } from "./types";

// -- Coordinates ------------------------------------------------------------------

// "00 42 44.3", "0:42:44", "0h42m44s", "41°16′9″" or a decimal ("0.712", "0,712"):
// up to three numbers, each part below 60 after the first; a sign only in front.
export function parseSexagesimal(text: string): number | null {
  let rest = text.trim().replace(/−/g, "-");
  let sign = 1;
  if (rest.startsWith("-") || rest.startsWith("+")) {
    sign = rest.startsWith("-") ? -1 : 1;
    rest = rest.slice(1);
  }
  const parts = rest
    .replace(/[hdms°'′"″:]/gi, " ")
    .trim()
    .split(/\s+/)
    .filter((part) => part !== "");
  if (parts.length === 0 || parts.length > 3) return null;
  const numbers = parts.map((part) => (/^\d+([.,]\d*)?$/.test(part) ? Number(part.replace(",", ".")) : NaN));
  if (numbers.some((n) => !Number.isFinite(n)) || numbers.slice(1).some((n) => n >= 60)) return null;
  const [whole = 0, minutes = 0, seconds = 0] = numbers;
  return sign * (whole + minutes / 60 + seconds / 3600);
}

// Right ascension in hours, 0 to 24.
export function parseRa(text: string): number | null {
  if (/^\s*[-+−]/.test(text)) return null;
  const hours = parseSexagesimal(text);
  return hours !== null && hours < 24 ? hours : null;
}

// Declination in degrees, -90 to 90.
export function parseDec(text: string): number | null {
  const degrees = parseSexagesimal(text);
  return degrees !== null && Math.abs(degrees) <= 90 ? degrees : null;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatRa(hours: number): string {
  const total = Math.round((((hours % 24) + 24) % 24) * 3600) % 86400;
  return `${pad2(Math.floor(total / 3600))}h ${pad2(Math.floor(total / 60) % 60)}m ${pad2(total % 60)}s`;
}

export function formatDec(degrees: number): string {
  const total = Math.round(Math.abs(degrees) * 3600);
  const sign = degrees < 0 && total > 0 ? "−" : "+";
  return `${sign}${pad2(Math.floor(total / 3600))}° ${pad2(Math.floor(total / 60) % 60)}′ ${pad2(total % 60)}″`;
}

// -- State ----------------------------------------------------------------------------

// What the mount is doing, in words, and whether anything moves it now.
export function mountActivity(mount: MountState, t: Messages): { text: string; moving: boolean } {
  if (mount.parking) return { text: mount.parked ? t.mount.unparking : t.mount.parking, moving: true };
  if (mount.homing) return { text: t.mount.homing, moving: true };
  if (mount.slewing) return { text: t.mount.slewing, moving: true };
  if (mount.moving.ns || mount.moving.we) return { text: t.mount.moving, moving: true };
  if (mount.parked) return { text: t.mount.parked, moving: false };
  return { text: mount.tracking ? t.mount.tracking : t.mount.still, moving: false };
}

// -- Slew pad ---------------------------------------------------------------------------

export type Direction = "north" | "south" | "east" | "west";

export const KEEPALIVE_MS = 250;
const RECONNECT_MS = 1000;

// One pad's WebSocket. While a direction is held it repeats the whole state
// every KEEPALIVE_MS; the server stops the mount when they stop coming, when the
// socket closes, and on any error, and then waits for a release before moving
// again ("latched"). Letting go of everything sends one release.
export class PadLink {
  status = $state<PadStatusMessage | null>(null);
  connected = $state(false);
  // Directions held now, for the buttons to show.
  held = $state<Direction[]>([]);
  #socket: WebSocket | null = null;
  #wanted = false;
  #order = new Map<Direction, number>();
  #count = 0;
  #rate: string | null = null;
  #keepalive: ReturnType<typeof setInterval> | null = null;
  #retry: ReturnType<typeof setTimeout> | null = null;

  open(): void {
    this.#wanted = true;
    this.#connect();
  }

  close(): void {
    this.#wanted = false;
    this.releaseAll();
    if (this.#retry) clearTimeout(this.#retry);
    this.#socket?.close();
    this.#socket = null;
    this.connected = false;
  }

  setRate(rate: string | null): void {
    this.#rate = rate;
    if (this.#order.size > 0) this.#send();
  }

  press(direction: Direction): void {
    if (this.#order.has(direction)) return;
    this.#order.set(direction, ++this.#count);
    this.held = [...this.#order.keys()];
    this.#send();
    this.#keepalive ??= setInterval(() => this.#send(), KEEPALIVE_MS);
  }

  release(direction: Direction): void {
    if (!this.#order.delete(direction)) return;
    this.held = [...this.#order.keys()];
    this.#send();
    if (this.#order.size === 0) this.#stopKeepalive();
  }

  // The page went to the background, the window lost focus, the socket closed.
  releaseAll(): void {
    if (this.#order.size === 0) return;
    this.#order.clear();
    this.held = [];
    this.#send();
    this.#stopKeepalive();
  }

  #stopKeepalive(): void {
    if (this.#keepalive) clearInterval(this.#keepalive);
    this.#keepalive = null;
  }

  // The latest held direction of each axis wins.
  #request(): PadRequest {
    const latest = (a: Direction, b: Direction): Direction | null => {
      const first = this.#order.get(a) ?? 0;
      const second = this.#order.get(b) ?? 0;
      if (!first && !second) return null;
      return first > second ? a : b;
    };
    return {
      ns: latest("north", "south") as PadRequest["ns"],
      we: latest("west", "east") as PadRequest["we"],
      rate: this.#rate,
    };
  }

  #send(): void {
    if (this.#socket?.readyState === WebSocket.OPEN) this.#socket.send(JSON.stringify(this.#request()));
  }

  #connect(): void {
    if (!this.#wanted || this.#socket) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/api/mount/pad`);
    this.#socket = socket;
    socket.onopen = () => {
      this.connected = true;
      if (this.#order.size > 0) this.#send();
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        this.status = JSON.parse(event.data) as PadStatusMessage;
      } catch {
        // Not ours to interpret; the next status replaces it.
      }
    };
    socket.onclose = () => {
      // The server stopped the mount already; nothing held survives a new socket.
      this.#socket = null;
      this.connected = false;
      this.#order.clear();
      this.held = [];
      this.#stopKeepalive();
      if (this.#wanted) this.#retry = setTimeout(() => this.#connect(), RECONNECT_MS);
    };
  }
}
