// The countries whose Wi-Fi channels the radio knows (ADR 0028): the kernel's
// regulatory database, as the server's schema lists them (WifiCountry). The types
// keep this list and the schema's the same.

import type { WifiCountry } from "./types";

export const COUNTRIES = [
  "AD", "AE", "AF", "AI", "AL", "AM", "AN", "AR", "AS", "AT", "AU", "AW", "AZ", "BA", "BB", "BD", "BE", "BF",
  "BG", "BH", "BL", "BM", "BN", "BO", "BR", "BS", "BT", "BW", "BY", "BZ", "CA", "CF", "CH", "CI", "CL", "CN",
  "CO", "CR", "CU", "CX", "CY", "CZ", "DE", "DK", "DM", "DO", "DZ", "EC", "EE", "EG", "ES", "ET", "FI", "FM",
  "FO", "FR", "GB", "GD", "GE", "GF", "GH", "GI", "GL", "GP", "GR", "GT", "GU", "GY", "HK", "HN", "HR", "HT",
  "HU", "ID", "IE", "IL", "IM", "IN", "IR", "IS", "IT", "JM", "JO", "JP", "KE", "KH", "KN", "KP", "KR", "KW",
  "KY", "KZ", "LB", "LC", "LI", "LK", "LS", "LT", "LU", "LV", "MA", "MC", "MD", "ME", "MF", "MH", "MK", "MN",
  "MO", "MP", "MQ", "MR", "MT", "MU", "MV", "MW", "MX", "MY", "NA", "NG", "NI", "NL", "NO", "NP", "NZ", "OM",
  "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM", "PR", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
  "SA", "SE", "SG", "SI", "SK", "SM", "SN", "SR", "SV", "SX", "SY", "TC", "TD", "TG", "TH", "TN", "TR", "TT",
  "TW", "TZ", "UA", "UG", "US", "UY", "UZ", "VA", "VC", "VE", "VI", "VN", "VU", "WF", "WS", "YE", "YT", "ZA",
  "ZW"
] as const satisfies readonly WifiCountry[];

// Does not compile when the schema has a country this list lacks.
export const EVERY_COUNTRY: [Exclude<WifiCountry, (typeof COUNTRIES)[number]>] extends [never] ? true : false = true;

export function isCountry(code: string): code is WifiCountry {
  return (COUNTRIES as readonly string[]).includes(code);
}

export type CountryChoice = { code: WifiCountry; name: string };

// Every country by its name in the app's language, sorted by it.
export function countryChoices(locale: string): CountryChoice[] {
  const names = new Intl.DisplayNames([locale], { type: "region" });
  return COUNTRIES.map((code) => ({ code, name: names.of(code) ?? code })).sort((a, b) =>
    a.name.localeCompare(b.name, locale),
  );
}
