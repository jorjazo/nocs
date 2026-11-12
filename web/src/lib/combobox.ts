// The keys that move through a combobox's options (WAI-ARIA combobox pattern): the
// index of the option they make active, or null for a key the list leaves alone
// (Home and End move the caret in the field). -1 is no active option.
const PAGE = 10;

export function moveActive(key: string, active: number, count: number): number | null {
  if (count === 0) return null;
  switch (key) {
    case "ArrowDown":
      return active < 0 ? 0 : (active + 1) % count;
    case "ArrowUp":
      return active <= 0 ? count - 1 : active - 1;
    case "PageDown":
      return Math.min(Math.max(active, 0) + PAGE, count - 1);
    case "PageUp":
      return Math.max(active - PAGE, 0);
    default:
      return null;
  }
}
