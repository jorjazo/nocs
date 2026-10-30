// Hash router (#/rig): nocsd serves the built files as they are, without a
// fallback to index.html, so reloading any screen must not need the server.

export type Tab = "tonight" | "live" | "plan" | "session" | "rig";
export const TABS: readonly Tab[] = ["tonight", "live", "plan", "session", "rig"];

export type Route = { screen: Tab } | { screen: "dev" };

const DEFAULT: Route = { screen: "tonight" };

function parse(hash: string): Route {
  const [first] = hash.replace(/^#\/?/, "").split("/");
  if (first === "dev") return { screen: "dev" };
  const tab = TABS.find((name) => name === first);
  return tab ? { screen: tab } : DEFAULT;
}

export function href(route: Route): string {
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
