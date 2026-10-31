// Hash router (#/rig): nocsd serves the built files as they are, without a
// fallback to index.html, so reloading any screen must not need the server.

export type Tab = "tonight" | "live" | "plan" | "session" | "rig";
export const TABS: readonly Tab[] = ["tonight", "live", "plan", "session", "rig"];

// The profile editor hangs off Rig: #/rig/profile/<id>, or #/rig/profile/new.
export type Route = { screen: Tab } | { screen: "dev" } | { screen: "profile"; id: string | null };

const DEFAULT: Route = { screen: "tonight" };

function parse(hash: string): Route {
  const [first, second, third] = hash.replace(/^#\/?/, "").split("/");
  if (first === "dev") return { screen: "dev" };
  if (first === "rig" && second === "profile" && third) {
    return { screen: "profile", id: third === "new" ? null : decodeURIComponent(third) };
  }
  const tab = TABS.find((name) => name === first);
  return tab ? { screen: tab } : DEFAULT;
}

export function href(route: Route): string {
  if (route.screen === "profile") return `#/rig/profile/${route.id === null ? "new" : encodeURIComponent(route.id)}`;
  return `#/${route.screen}`;
}

class Router {
  route: Route = $state(parse(location.hash));

  constructor() {
    addEventListener("hashchange", () => {
      this.route = parse(location.hash);
    });
  }

  go(route: Route): void {
    location.hash = href(route);
  }
}

export const router = new Router();
