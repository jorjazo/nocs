// Minimal typed i18n: `i18n.t` is the message catalog of the current locale,
// reactive through prefs.locale, so switching language needs no reload.

import { type Locale, prefs } from "../prefs.svelte";
import { en, type Messages } from "./en";
import { es } from "./es";

const catalogs: Record<Locale, Messages> = { en, es };

export const LANGUAGE_NAMES: Record<Locale, string> = { en: "English", es: "Español" };

export const i18n = {
  get t(): Messages {
    return catalogs[prefs.locale];
  },
  get locale(): Locale {
    return prefs.locale;
  },
};

export type { Locale, Messages };
