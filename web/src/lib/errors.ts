import { ApiError } from "./api";
import type { Messages } from "./i18n";

// What to tell the user about a failed request. Server details are specific
// (and in English); requests that never reached nocsd get a translated message.
export function errorText(e: unknown, t: Messages): string {
  if (e instanceof ApiError) {
    if (e.network) return t.errors.network;
    return e.message || t.errors.server(e.status);
  }
  return e instanceof Error ? e.message : String(e);
}
