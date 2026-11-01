// The appliance's first run (ADR 0028): shown while the access point keeps its
// default password, and kept up after saving so that its instructions stay on
// screen until the user moves on.

export type SetupDone = { ssid: string | null; accessPoint: string; host: string };

class BoxSetup {
  done: SetupDone | null = $state(null);
}

export const boxSetup = new BoxSetup();

// The country of the browser's language (es-CL → CL), to start the form with.
export function guessCountry(): string {
  try {
    return new Intl.Locale(navigator.language).maximize().region ?? "";
  } catch {
    return "";
  }
}
