// Hash router (#/rig): nocsd serves the built files as they are, without a
// fallback to index.html, so reloading any screen must not need the server.

import { isRigSection, type RigSection } from "./rigsections";

export type Tab = "tonight" | "explore" | "sequence" | "plan" | "video" | "visits" | "session" | "rig";
export const TABS: readonly Tab[] = ["tonight", "explore", "sequence", "plan", "video", "visits", "session", "rig"];

// Rig opens one of its sections, scrolled to it, at #/rig/<section> (#/rig/site).
// The profile editor hangs off Rig: #/rig/profile/<id>, or #/rig/profile/new, and
// so does a site's: #/rig/site/<id>, or #/rig/site/new; off Plan, its targets
// (#/plan/edit), adding one (#/plan/add), a catalog object's page to add it
// (#/plan/object/<catalog id>), one from coordinates (#/plan/new) and a target's own
// page (#/plan/target/<id>); the sequence's groups off Sequences: #/sequence/edit; a
// session's report off Session: #/session/<id>.
// Autofocus (#/focus) and the focuser's calibration (#/focus/calibrate), guiding
// (#/guiding), polar alignment (#/polar) and flats
// (#/flats, or #/flats/<night> for that night's lights) are full-screen flows
// over whichever tab opened them.
export type Route =
  | { screen: Exclude<Tab, "rig"> }
  | { screen: "rig"; section?: RigSection }
  | { screen: "dev" }
  | { screen: "focus" }
  | { screen: "focus-calibration" }
  | { screen: "guiding" }
  | { screen: "sequence-edit" }
  | { screen: "plan-edit" }
  | { screen: "plan-add" }
  | { screen: "plan-new" }
  | { screen: "plan-target"; id: string }
  | { screen: "report"; id: number }
  | { screen: "polar" }
  | { screen: "flats"; night: number | null }
  | { screen: "profile"; id: string | null }
  | { screen: "site"; id: string | null }
  | { screen: "target"; id: string };

const DEFAULT: Route = { screen: "tonight" };

function parse(hash: string): Route {
  const [first, second, third] = hash.replace(/^#\/?/, "").split("/");
  if (first === "dev") return { screen: "dev" };
  if (first === "focus" && second === "calibrate") return { screen: "focus-calibration" };
  if (first === "focus") return { screen: "focus" };
  if (first === "guiding") return { screen: "guiding" };
  if (first === "polar") return { screen: "polar" };
  if (first === "flats") return { screen: "flats", night: second && /^\d+$/.test(second) ? Number(second) : null };
  if (first === "sequence" && second === "edit") return { screen: "sequence-edit" };
  if (first === "session" && second && /^\d+$/.test(second)) return { screen: "report", id: Number(second) };
  if (first === "plan" && second === "edit") return { screen: "plan-edit" };
  if (first === "plan" && second === "add") return { screen: "plan-add" };
  if (first === "plan" && second === "new") return { screen: "plan-new" };
  if (first === "plan" && second === "object" && third) return { screen: "target", id: decodeURIComponent(third) };
  if (first === "plan" && second === "target" && third) return { screen: "plan-target", id: decodeURIComponent(third) };
  if (first === "rig" && second === "profile" && third) {
    return { screen: "profile", id: third === "new" ? null : decodeURIComponent(third) };
  }
  if (first === "rig" && second === "site" && third) {
    return { screen: "site", id: third === "new" ? null : decodeURIComponent(third) };
  }
  if (first === "rig" && second && !third && isRigSection(second)) return { screen: "rig", section: second };
  const tab = TABS.find((name) => name === first);
  return tab ? { screen: tab } : DEFAULT;
}

export function href(route: Route): string {
  if (route.screen === "profile") return `#/rig/profile/${route.id === null ? "new" : encodeURIComponent(route.id)}`;
  if (route.screen === "site") return `#/rig/site/${route.id === null ? "new" : encodeURIComponent(route.id)}`;
  if (route.screen === "target") return `#/plan/object/${encodeURIComponent(route.id)}`;
  if (route.screen === "plan-target") return `#/plan/target/${encodeURIComponent(route.id)}`;
  if (route.screen === "plan-edit") return "#/plan/edit";
  if (route.screen === "plan-add") return "#/plan/add";
  if (route.screen === "plan-new") return "#/plan/new";
  if (route.screen === "sequence-edit") return "#/sequence/edit";
  if (route.screen === "focus-calibration") return "#/focus/calibrate";
  if (route.screen === "report") return `#/session/${route.id}`;
  if (route.screen === "rig" && route.section) return `#/rig/${route.section}`;
  if (route.screen === "flats") return route.night === null ? "#/flats" : `#/flats/${route.night}`;
  return `#/${route.screen}`;
}

class Router {
  route: Route = $state(parse(location.hash));
  // Where a full-screen flow was opened from, to return there when it closes.
  private previous: Route | null = null;

  constructor() {
    addEventListener("hashchange", () => {
      this.previous = this.route;
      this.route = parse(location.hash);
    });
  }

  go(route: Route): void {
    location.hash = href(route);
  }

  // Back to the screen before this one, or to `fallback` when the page was
  // opened here (a reload, a bookmark).
  back(fallback: Route): void {
    const target = this.previous && this.previous.screen !== this.route.screen ? this.previous : fallback;
    this.go(target);
  }
}

export const router = new Router();
