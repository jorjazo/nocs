// How wide a screen's page may grow (docs/ux.md §5, "Breakpoints and page width").
//
// - "narrow": one readable column, at most --page-width (forms, lists, settings).
// - "wide": from 1200 px, up to --page-width-wide, for screens laid out in columns
//   that use the space of a PC's screen (Session).
// - "full": edge to edge, without the page's margins (Live view's preview).
//
// Below 1200 px "wide" is the same as "narrow": phones and tablets do not change.
import type { Route } from "./router.svelte";

export type PageWidth = "narrow" | "wide" | "full";

export function pageWidth(route: Route): PageWidth {
  if (route.screen === "live") return "full";
  if (route.screen === "session") return "wide";
  return "narrow";
}
