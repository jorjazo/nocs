// Where a new site's position can come from (ADR 0038, ADR 0042): the mount's own
// site (its driver's GEOGRAPHIC_COORD, as the state publishes it) or a USB GPS's fix
// (gpsd, ADR 0029). Each source gives a position, or the reason it cannot.

import type { GpsState, MountState, Site } from "./types";

export type Position = { latitude: number; longitude: number; elevation: number | null };

export type SourceProblem = "noMount" | "noMountSite" | "mountUnset" | "noGps" | "noFix";

export type Source =
  | {
      position: Position;
      // The saved site within NEAR of it (another one than the site being edited).
      near: string | null;
    }
  | { problem: SourceProblem };

// Metres on the ground within which a position is at a saved site, as the server
// matches a GPS fix (`nocs.sites.NEAR`).
export const NEAR = 500;
const EARTH_RADIUS_M = 6_371_000;

// Metres on the ground between two positions (haversine, a spherical Earth), as the
// server computes it (`nocs.sites.distance`).
export function distance(a: { latitude: number; longitude: number }, b: { latitude: number; longitude: number }): number {
  const radians = Math.PI / 180;
  const phi1 = a.latitude * radians;
  const phi2 = b.latitude * radians;
  const dphi = phi2 - phi1;
  const dlambda = (b.longitude - a.longitude) * radians;
  const h = Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

// The saved site nearest to a position within NEAR, leaving out `except` (the site
// being edited, which may well be where it already is).
export function nearestSite(
  saved: Readonly<Record<string, Site>>,
  position: { latitude: number; longitude: number },
  except: string | null = null,
): string | null {
  let best: { id: string; metres: number } | null = null;
  for (const [id, site] of Object.entries(saved)) {
    if (id === except) continue;
    const metres = distance(site, position);
    if (metres <= NEAR && (best === null || metres < best.metres)) best = { id, metres };
  }
  return best?.id ?? null;
}

// A position as a site keeps it: degrees to 6 decimals (about 10 cm), whole metres.
function rounded(latitude: number, longitude: number, elevation: number | null): Position {
  const round6 = (value: number) => Math.round(value * 1e6) / 1e6;
  return {
    latitude: round6(latitude),
    longitude: round6(longitude),
    elevation: elevation === null ? null : Math.round(elevation),
  };
}

// The connected mount's own site. A driver that never got one reports 0°, 0° (in the
// Gulf of Guinea): that is no site at all. Right after NOCS sent the box's active
// site, it is that site again, which `near` then names.
export function mountSource(
  mount: MountState | null | undefined,
  saved: Readonly<Record<string, Site>>,
  except: string | null = null,
): Source {
  if (!mount) return { problem: "noMount" };
  const site = mount.site;
  if (!site) return { problem: "noMountSite" };
  if (site.latitude === 0 && site.longitude === 0) return { problem: "mountUnset" };
  const position = rounded(site.latitude, site.longitude, site.elevation);
  return { position, near: nearestSite(saved, position, except) };
}

// A USB GPS's fix: 2D gives the latitude and longitude only, 3D the elevation too.
export function gpsSource(
  gps: GpsState | null | undefined,
  saved: Readonly<Record<string, Site>>,
  except: string | null = null,
): Source {
  if (!gps?.connected) return { problem: "noGps" };
  if (gps.fix === "none" || gps.latitude === null || gps.longitude === null) return { problem: "noFix" };
  const position = rounded(gps.latitude, gps.longitude, gps.fix === "3d" ? gps.elevation : null);
  return { position, near: nearestSite(saved, position, except) };
}
