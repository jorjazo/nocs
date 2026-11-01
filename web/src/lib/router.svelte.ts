// Hash router (#/rig): nocsd serves the built files as they are, without a
// fallback to index.html, so reloading any screen must not need the server.

export type Tab = "tonight" | "live" | "plan" | "session" | "rig";
export const TABS: readonly Tab[] = ["tonight", "live", "plan", "session", "rig"];

// The profile editor hangs off Rig: #/rig/profile/<id>, or #/rig/profile/new; a
// target's page off Plan: #/plan/<catalog id>, and the sequence builder:
// #/plan/sequence (no catalog id is "sequence"); a session's report off Session:
// #/session/<id>.
// Autofocus (#/focus), guiding (#/guiding), polar alignment (#/polar) and flats
// (#/flats, or #/flats/<night> for that night's lights) are full-screen flows
// over whichever tab opened them.
export type Route =
  | { screen: Tab }
  | { screen: "dev" }
  | { screen: "focus" }
  | { screen: "guiding" }
  | { screen: "sequence" }
  | { screen: "report"; id: number }
  | { screen: "polar" }
  | { screen: "flats"; night: number | null }
  | { screen: "profile"; id: string | null }
  | { screen: "target"; id: string };

const DEFAULT: Route = { screen: "tonight" };

function parse(hash: string): Route {
  const [first, second, third] = hash.replace(/^#\/?/, "").split("/");
  if (first === "dev") return { screen: "dev" };
  if (first === "focus") return { screen: "focus" };
  if (first === "guiding") return { screen: "guiding" };
  if (first === "polar") return { screen: "polar" };
  if (first === "flats") return { screen: "flats", night: second && /^\d+$/.test(second) ? Number(second) : null };
  if (first === "plan" && second === "sequence") return { screen: "sequence" };
  if (first === "session" && second && /^\d+$/.test(second)) return { screen: "report", id: Number(second) };
  if (first === "plan" && second) return { screen: "target", id: decodeURIComponent(second) };
  if (first === "rig" && second === "profile" && third) {
    return { screen: "profile", id: third === "new" ? null : decodeURIComponent(third) };
  }
  const tab = TABS.find((name) => name === first);
  return tab ? { screen: tab } : DEFAULT;
}

export function href(route: Route): string {
  if (route.screen === "profile") return `#/rig/profile/${route.id === null ? "new" : encodeURIComponent(route.id)}`;
  if (route.screen === "target") return `#/plan/${encodeURIComponent(route.id)}`;
  if (route.screen === "sequence") return "#/plan/sequence";
  if (route.screen === "report") return `#/session/${route.id}`;
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
