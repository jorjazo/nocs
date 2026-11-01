// Per-device preferences: theme, language, and whether the framing chart may
// fetch survey images from the internet. They are about this screen, not the
// rig, so they live in the browser rather than on the server.

export type Theme = "dusk" | "night";
export type Locale = "en" | "es";

export const THEMES: readonly Theme[] = ["dusk", "night"];
export const LOCALES: readonly Locale[] = ["en", "es"];

// The browser's top bar follows the theme (Android Chrome, Safari).
const THEME_COLOR: Record<Theme, string> = { dusk: "#0A0D13", night: "#000000" };

function read<T extends string>(key: string, allowed: readonly T[]): T | null {
  try {
    const value = localStorage.getItem(key);
    return allowed.find((item) => item === value) ?? null;
  } catch {
    return null; // storage blocked (private mode): fall back to defaults
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Not persisted; the choice still applies until the page reloads.
  }
}

function browserLocale(): Locale {
  for (const language of navigator.languages) {
    const base = language.slice(0, 2).toLowerCase();
    const match = LOCALES.find((locale) => locale === base);
    if (match) return match;
  }
  return "en";
}

class Prefs {
  theme: Theme = $state(read("nocs.theme", THEMES) ?? "dusk");
  locale: Locale = $state(read("nocs.locale", LOCALES) ?? browserLocale());
  // Off until the user turns it on: the rig is often offline, and it asks CDS.
  survey: boolean = $state(read("nocs.survey", ["on"] as const) === "on");
  // The user's own solved frames under the chart: on unless turned off (they come from nocsd).
  ownFrames: boolean = $state(read("nocs.ownFrames", ["off"] as const) !== "off");

  constructor() {
    this.#apply();
  }

  setTheme(theme: Theme): void {
    this.theme = theme;
    write("nocs.theme", theme);
    this.#apply();
  }

  toggleTheme(): void {
    this.setTheme(this.theme === "night" ? "dusk" : "night");
  }

  setLocale(locale: Locale): void {
    this.locale = locale;
    write("nocs.locale", locale);
    this.#apply();
  }

  setSurvey(on: boolean): void {
    this.survey = on;
    write("nocs.survey", on ? "on" : "off");
  }

  setOwnFrames(on: boolean): void {
    this.ownFrames = on;
    write("nocs.ownFrames", on ? "on" : "off");
  }

  #apply(): void {
    const root = document.documentElement;
    root.dataset.theme = this.theme;
    root.lang = this.locale;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[this.theme]);
  }
}

export const prefs = new Prefs();
