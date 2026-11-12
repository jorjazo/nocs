// Where this client stands with the server (ADR 0014): setup mode, unpaired,
// observer or owner. The app shows first run, pairing or the screens from it.

import { ApiError, getAuth, pair, redeemHandoff, revokeDevice, setUnauthorizedHandler, setUp } from "./api";
import { takeHandoff } from "./handoff";
import type { AuthStatus } from "./types";

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, e instanceof Error ? e.message : String(e));
}

class Auth {
  status: AuthStatus | null = $state(null);
  // Why the last GET /api/auth failed; the last known status is kept meanwhile.
  error: ApiError | null = $state(null);
  // This device was unpaired while in use: pairing says so.
  revoked = $state(false);
  // An observer asked to pair (or was revoked): show pairing even though it may watch.
  wantsPair = $state(false);
  // A pairing handed over from the box's old name could not be taken (ADR 0044).
  handoffFailed = $state(false);
  #refreshing: Promise<void> | null = null;

  constructor() {
    setUnauthorizedHandler(() => void this.refresh());
  }

  get owner(): boolean {
    return this.status?.role === "owner";
  }

  // The page's first look at the server. A pairing handed over from the box's old
  // name (ADR 0044) leaves the URL at once, then pairs this browser as that device.
  async start(): Promise<void> {
    const { token, hash } = takeHandoff(location.hash);
    if (token !== null) {
      history.replaceState(history.state, "", `${location.pathname}${location.search}${hash}`);
      try {
        await redeemHandoff(token);
      } catch {
        this.handoffFailed = true;
      }
    }
    await this.refresh();
  }

  refresh(): Promise<void> {
    this.#refreshing ??= this.#fetch().finally(() => (this.#refreshing = null));
    return this.#refreshing;
  }

  async #fetch(): Promise<void> {
    try {
      this.status = await getAuth();
      this.error = null;
      if (this.status.role === "owner") {
        this.revoked = false;
        this.wantsPair = false;
        this.handoffFailed = false;
      }
    } catch (e) {
      this.error = asApiError(e);
    }
  }

  // Setting up the passphrase also pairs this device.
  async setUp(passphrase: string, name: string): Promise<void> {
    await setUp({ passphrase, name });
    await this.refresh();
  }

  async pair(passphrase: string, name: string): Promise<void> {
    await pair({ passphrase, name });
    await this.refresh();
  }

  async unpair(): Promise<void> {
    const device = this.status?.device;
    if (!device) return;
    await revokeDevice(device.id);
    this.wantsPair = true;
    await this.refresh();
  }

  // The state channel was closed because our access ended.
  async onRevoked(): Promise<void> {
    this.revoked = true;
    this.wantsPair = true;
    await this.refresh();
  }
}

export const auth = new Auth();
