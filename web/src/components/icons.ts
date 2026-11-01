// In-house icons (docs/ux.md §6): 24 px grid, drawn as strokes of 1.8 px
// with round caps and joins. Each icon is a list of path data.

function circle(cx: number, cy: number, r: number): string {
  return `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
}

export const ICONS = {
  logo: [circle(12, 12, 9), "M12 3v4M12 17v4M3 12h4M17 12h4", circle(12, 12, 0.9)],
  tonight: ["M4 6h13M4 11h13M4 16h6", "M14 17.5l2.5 2.5 4.5-5"],
  live: [
    "M4 8.5A1.5 1.5 0 0 1 5.5 7h2.3l1.4-2h5.6l1.4 2h2.3A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z",
    circle(12, 13, 3.5),
  ],
  plan: [circle(12, 12, 6.5), "M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4", circle(12, 12, 0.9)],
  session: ["M3 12h4l2.5-6.5 5 13 2.5-6.5h4"],
  rig: ["M4 8h16M4 16h16M15 5v6M9 13v6"],
  camera: [
    "M4 8.5A1.5 1.5 0 0 1 5.5 7h2.3l1.4-2h5.6l1.4 2h2.3A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z",
    circle(12, 13, 3.5),
  ],
  mount: ["M5 9.5l11-5 1.8 3.8-11 5z", "M11.5 11.5l-4 9M11.5 11.5l4 9M11.5 11.5v3"],
  guide: [circle(12, 12, 7), circle(12, 12, 1.8), "M12 2.5v3.5M12 18v3.5M2.5 12H6M18 12h3.5"],
  focus: ["M4 9V5h4M16 5h4v4M20 15v4h-4M8 19H4v-4", "M12 9v6M9 12h6"],
  filter: [circle(12, 12, 8.5), circle(12, 8.3, 1.8), circle(8.6, 14.2, 1.8), circle(15.4, 14.2, 1.8)],
  power: ["M13.5 3L5.5 13.5h6l-1 7.5 8-10.5h-6z"],
  weather: ["M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z", "M12 11v6", "M17.5 6.5h2.5M17.5 10h2.5"],
  night: ["M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"],
  storage: ["M4 14h16v5.5H4z", "M5.5 14L8 5h8l2.5 9", "M16.5 16.8h.01"],
  server: ["M4 4.5h16v6H4zM4 13.5h16v6H4z", "M7.5 7.5h.01M7.5 16.5h.01"],
  device: ["M8 3h8a1.5 1.5 0 0 1 1.5 1.5v15A1.5 1.5 0 0 1 16 21H8a1.5 1.5 0 0 1-1.5-1.5v-15A1.5 1.5 0 0 1 8 3z", "M11 18h2"],
  eye: ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z", circle(12, 12, 2.8)],
  eyeOff: ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z", circle(12, 12, 2.8), "M4 4l16 16"],
  chevronDown: ["M6.5 9.5l5.5 5.5 5.5-5.5"],
  chevronRight: ["M9.5 6.5l5.5 5.5-5.5 5.5"],
  chevronLeft: ["M14.5 6.5L9 12l5.5 5.5"],
  offline: ["M3 3l18 18", "M8.5 16.3a5 5 0 0 1 7 0", "M5 12.6a10 10 0 0 1 3.8-2.3M19 12.6a10 10 0 0 0-3.2-2", "M2 9a14.5 14.5 0 0 1 4.2-2.7M22 9a14.5 14.5 0 0 0-9-3.6", "M12 20h.01"],
  alert: [circle(12, 12, 9), "M12 7.5v5.5M12 16.5h.01"],
  loop: ["M16.5 3.5l3 3-3 3", "M19.5 6.5H8.5A4.5 4.5 0 0 0 4 11v.5", "M7.5 20.5l-3-3 3-3", "M4.5 17.5h11A4.5 4.5 0 0 0 20 13v-.5"],
  save: [
    "M5.5 4h10l4 4v10.5a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4z",
    "M8 4v4h7V4",
    "M8 20v-6h8v6",
  ],
  expand: ["M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"],
  shrink: ["M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5"],
  close: ["M6 6l12 12M18 6L6 18"],
  plus: ["M12 5v14M5 12h14"],
  minus: ["M5 12h14"],
  download: ["M12 4v11", "M7 10.5l5 5 5-5", "M5 20h14"],
  up: ["M6 15l6-6 6 6"],
  down: ["M6 9l6 6 6-6"],
  left: ["M15 6l-6 6 6 6"],
  right: ["M9 6l6 6-6 6"],
  home: ["M4 11l8-6.5 8 6.5", "M6.5 9.5V19.5h11V9.5", "M10 19.5v-5h4v5"],
  park: [circle(12, 12, 9), "M9.5 16.5v-9h3.5a2.75 2.75 0 0 1 0 5.5H9.5"],
} satisfies Record<string, string[]>;

export type IconName = keyof typeof ICONS;
