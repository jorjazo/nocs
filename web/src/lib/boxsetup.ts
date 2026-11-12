// The steps of the box's first run (ADR 0028) and the checks each one makes before
// the next, kept apart from the screen so that a later step (the site, say) is one
// more entry here and its own section on the screen.

export type SetupStep = "accessPoint" | "wifi" | "name" | "review";

// The steps shown: the name only where nocs-system may rename the box; the review,
// where nothing is applied yet, always last.
export function setupSteps(options: { rename: boolean }): SetupStep[] {
  const steps: SetupStep[] = ["accessPoint", "wifi"];
  if (options.rename) steps.push("name");
  steps.push("review");
  return steps;
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
