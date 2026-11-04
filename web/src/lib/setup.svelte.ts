// The appliance's first run (ADR 0028): shown while the access point keeps its
// default password, and kept up after saving so that its instructions stay on
// screen until the user moves on.

export type SetupDone = { ssid: string | null; accessPoint: string; host: string };

class BoxSetup {
  done: SetupDone | null = $state(null);
}

export const boxSetup = new BoxSetup();

// The country of the browser's languages (es-CL → CL), to start the form with. A
// region that is not a country (es-419, Latin America) is skipped.
export function guessCountry(): string {
  for (const language of [...(navigator.languages ?? []), navigator.language]) {
    try {
      const region = new Intl.Locale(language).maximize().region ?? "";
      if (/^[A-Z]{2}$/.test(region)) return region;
    } catch {
      // not a language tag: try the next one
    }
  }
  return "";
}
