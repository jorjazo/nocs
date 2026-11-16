// Tonight's sections (docs/ux.md §1): which ones there are, which start open, and
// where the get-ready checklist goes. Each card opens and closes, and the browser
// keeps which are open, except the checklist's: it opens on top while something is
// left to do, and closes at the bottom once all is done.

import { parseOpen, type OpenSections } from "./rigsections.ts";

export const TONIGHT_SECTIONS = ["preparation", "night", "target", "weather"] as const;
export type TonightSection = (typeof TONIGHT_SECTIONS)[number];

// The night is what the screen is for; the rest is a look now and then.
export const OPEN_BY_DEFAULT: readonly TonightSection[] = ["night"];

export { parseOpen, type OpenSections };

export function isOpen(open: OpenSections, section: TonightSection): boolean {
  return open[section] ?? OPEN_BY_DEFAULT.includes(section);
}

// The cards in order: the checklist first while something is left, last once done.
export function arrange(prepared: boolean): TonightSection[] {
  const rest = TONIGHT_SECTIONS.filter((section) => section !== "preparation");
  return prepared ? [...rest, "preparation"] : ["preparation", ...rest];
}
