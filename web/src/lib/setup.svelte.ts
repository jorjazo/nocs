// The appliance's first run (ADR 0028): shown until nocs-system records it
// (`network.set_up`), and kept up after applying so that its instructions stay on
// screen until the user moves on.

import { isCountry } from "./countries";

export type SetupDone = {
  ssid: string | null;
  accessPoint: string;
  host: string;
  renamed: boolean;
  // The box was on its access point, which then restarts.
  onAp: boolean;
};

class BoxSetup {
  done: SetupDone | null = $state(null);
}

export const boxSetup = new BoxSetup();

// The country of the browser's languages (es-CL → CL), to start the form with. A
// region that is not a country the radio knows (es-419, Latin America) is skipped.
export function guessCountry(): string {
  for (const language of [...(navigator.languages ?? []), navigator.language]) {
    try {
      const region = new Intl.Locale(language).maximize().region ?? "";
      if (isCountry(region)) return region;
    } catch {
      // not a language tag: try the next one
    }
  }
  return "";
}
