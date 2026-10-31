// The framing chart's projection (ADR 0020): gnomonic (tangent plane, the one
// a camera's sensor makes, so a frame is a true rectangle), centred on the view,
// north up and east to the left as the sky is seen. RA in hours and Dec in
// degrees, J2000, like the rest of the API; screen points in CSS pixels.
//
// Self-contained (no imports) so `node --test` runs its tests as they are.

export type Sky = { ra: number; dec: number };
export type Point = { x: number; y: number };

export type View = {
  center: Sky;
  // CSS pixels per radian of the tangent plane (≈ per radian of sky at the centre).
  scale: number;
  width: number;
  height: number;
};

const RAD = Math.PI / 180;
const HOUR = 15 * RAD;

// Below this cosine of the distance to the centre (~84°) a point is not drawn:
// the projection runs to infinity at 90°.
const HORIZON = 0.1;

export function project(view: View, sky: Sky): Point | null {
  const d0 = view.center.dec * RAD;
  const d = sky.dec * RAD;
  const dra = (sky.ra - view.center.ra) * HOUR;
  const cosC = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(dra);
  if (cosC < HORIZON) return null;
  const xi = (Math.cos(d) * Math.sin(dra)) / cosC; // east
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(dra)) / cosC; // north
  return { x: view.width / 2 - xi * view.scale, y: view.height / 2 - eta * view.scale };
}

export function unproject(view: View, point: Point): Sky {
  const xi = (view.width / 2 - point.x) / view.scale;
  const eta = (view.height / 2 - point.y) / view.scale;
  const d0 = view.center.dec * RAD;
  const rho = Math.hypot(xi, eta);
  if (rho === 0) return { ...view.center };
  const c = Math.atan(rho);
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (eta * Math.sin(c) * Math.cos(d0)) / rho);
  const dra = Math.atan2(xi * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - eta * Math.sin(d0) * Math.sin(c));
  return { ra: wrapHours(view.center.ra + dra / HOUR), dec: dec / RAD };
}

// The view moved by a drag from `from` to `to`: the centre shifts on the
// tangent plane. Far from the centre the sky slides slightly under the finger
// (the plane turns as its tangent point moves), less than a pixel for the
// small steps pointer events come in.
export function pan(view: View, from: Point, to: Point): Sky {
  const center = unproject(view, { x: view.width / 2 + from.x - to.x, y: view.height / 2 + from.y - to.y });
  // Past a pole the chart would turn upside down: stop just short of it.
  const turn = Math.abs(wrapHours(center.ra - view.center.ra + 12) - 12);
  if (Math.abs(center.dec) > 85 && turn > 3) {
    return { ra: view.center.ra, dec: Math.sign(view.center.dec) * 89.9 };
  }
  return { ra: center.ra, dec: Math.max(-89.9, Math.min(89.9, center.dec)) };
}

// Screen directions of north and east at a sky point (unit vectors), which
// turn away from straight up and left off the centre.
export function axes(view: View, sky: Sky): { north: Point; east: Point } | null {
  const here = project(view, sky);
  const step = 1e-3; // degrees
  const up = sky.dec + step > 90 ? sky.dec - step : sky.dec + step;
  const north = project(view, { ra: sky.ra, dec: up });
  if (!here || !north) return null;
  const sign = up > sky.dec ? 1 : -1;
  const nx = (north.x - here.x) * sign;
  const ny = (north.y - here.y) * sign;
  const length = Math.hypot(nx, ny);
  if (length === 0) return null;
  // East is north turned a quarter left on screen (y grows downwards).
  return { north: { x: nx / length, y: ny / length }, east: { x: ny / length, y: -nx / length } };
}

// Canvas rotation (radians, clockwise from +x) of a direction given as a
// position angle (degrees east of north) at a sky point.
export function screenAngle(view: View, sky: Sky, positionAngle: number): number | null {
  const frame = axes(view, sky);
  if (!frame) return null;
  const pa = positionAngle * RAD;
  const x = frame.north.x * Math.cos(pa) + frame.east.x * Math.sin(pa);
  const y = frame.north.y * Math.cos(pa) + frame.east.y * Math.sin(pa);
  return Math.atan2(y, x);
}

// Corners of a camera frame centred on the view, `width` × `height` degrees,
// whose top points `rotation` degrees east of north (as a plate solution gives
// it, ADR 0018): top left, top right, bottom right, bottom left. The sensor is
// itself a tangent plane, so at the centre it is an exact rectangle, and its
// size (pixels × scale) is a length on that plane.
export function frameCorners(view: View, width: number, height: number, rotation: number): Point[] {
  const theta = rotation * RAD;
  // Top of the frame and its right side (west, for a frame that is not mirrored).
  const top = { x: -Math.sin(theta), y: -Math.cos(theta) };
  const right = { x: Math.cos(theta), y: -Math.sin(theta) };
  const halfWidth = ((width * RAD) / 2) * view.scale;
  const halfHeight = ((height * RAD) / 2) * view.scale;
  const cx = view.width / 2;
  const cy = view.height / 2;
  return [
    [-1, 1],
    [1, 1],
    [1, -1],
    [-1, -1],
  ].map(([sx = 0, sy = 0]) => ({
    x: cx + sx * halfWidth * right.x + sy * halfHeight * top.x,
    y: cy + sx * halfWidth * right.y + sy * halfHeight * top.y,
  }));
}

// Degrees between two sky points.
export function separation(a: Sky, b: Sky): number {
  const d1 = a.dec * RAD;
  const d2 = b.dec * RAD;
  const dra = (b.ra - a.ra) * HOUR;
  const h = Math.sin((d2 - d1) / 2) ** 2 + Math.cos(d1) * Math.cos(d2) * Math.sin(dra / 2) ** 2;
  return (2 * Math.asin(Math.min(1, Math.sqrt(h)))) / RAD;
}

// Degrees from the view's centre to its farthest corner.
export function viewRadius(view: View): number {
  return Math.atan(Math.hypot(view.width, view.height) / 2 / view.scale) / RAD;
}

// The scale that shows `degrees` across the view's shorter side.
export function scaleFor(degrees: number, width: number, height: number): number {
  return Math.min(width, height) / 2 / Math.tan((degrees * RAD) / 2);
}

// Degrees across the view's shorter side.
export function viewSpan(view: View): number {
  return (2 * Math.atan(Math.min(view.width, view.height) / 2 / view.scale)) / RAD;
}

export function wrapHours(ra: number): number {
  return ((ra % 24) + 24) % 24;
}
