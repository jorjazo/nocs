// The steps of the box's first run (ADR 0028) and the checks each one makes before
// the next, kept apart from the screen so that a later step is one more entry here
// and its own section on the screen.

export type SetupStep = "accessPoint" | "wifi" | "name" | "site" | "review";

// The steps shown: the name only where nocs-system may rename the box; the site,
// which may be left for later (ADR 0042); the review, where nothing is applied yet,
// always last.
export function setupSteps(options: { rename: boolean }): SetupStep[] {
  const steps: SetupStep[] = ["accessPoint", "wifi"];
  if (options.rename) steps.push("name");
  steps.push("site", "review");
  return steps;
}

// The site step's choice: a saved site's id, a new one, or none for now.
export type SiteChoice = { saved: string } | { new: SiteDraft } | null;

export type SiteDraft = { name: string; latitude: number | null; longitude: number | null; elevation: number | null };

// What the site step lacks before the next one, or null: a new site needs a name and
// a position (whose fields check their own ranges).
export function siteProblem(choice: SiteChoice): "name" | "position" | null {
  if (choice === null || "saved" in choice) return null;
  if (!choice.new.name.trim()) return "name";
  if (choice.new.latitude === null || choice.new.longitude === null) return "position";
  return null;
}

// One DNS label, as nocs-system checks it: the box is also <name>.local.
const HOSTNAME = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

// The host name as nocs-system will store it, or null when it refuses it.
export function hostName(name: string): string | null {
  const wanted = name.trim().toLowerCase();
  return HOSTNAME.test(wanted) ? wanted : null;
}

// A Wi-Fi password as nocs-system takes it: 8 to 63 ASCII characters, no control
// characters below the space.
export function wifiPassword(password: string): "short" | "long" | "ascii" | null {
  if (password.length < 8) return "short";
  if (password.length > 63) return "long";
  if (!/^[\x20-\x7f]*$/.test(password)) return "ascii";
  return null;
}
