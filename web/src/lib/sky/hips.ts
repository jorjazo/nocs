// HiPS tiles under the framing chart: which tiles a view needs, at which order,
// and how to draw one in the chart's gnomonic projection. A HiPS survey is the
// sky cut into HEALPix (nested) tiles, 512 px JPEGs, finer by 2 per order; the
// browser fetches the tiles itself and draws them here, so any field costs about
// the view's pixels, whatever its size (docs/spikes/survey-sources.md).

import { project, type Point, separation, type Sky, type View, viewRadius } from "./projection.ts";

const RAD = Math.PI / 180;
const HOUR = 15 * RAD;

// A tile: its order, base face (0–11) and place on that face.
export type Tile = { order: number; face: number; ix: number; iy: number };

const JRLL = [2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4];
const JPLL = [1, 3, 5, 7, 0, 2, 4, 6, 1, 3, 5, 7];

// A point of a base face, (x, y) in [0, 1] along the nested ix and iy bits: its
// right ascension (0–2π) and declination, radians (healpix_base's xyf2loc).
function faceToSky(face: number, x: number, y: number): { ra: number; dec: number } {
  const jr = (JRLL[face] ?? 0) - x - y;
  let nr: number;
  let z: number;
  if (jr < 1) {
    nr = jr;
    z = 1 - (nr * nr) / 3;
  } else if (jr > 3) {
    nr = 4 - jr;
    z = (nr * nr) / 3 - 1;
  } else {
    nr = 1;
    z = ((2 - jr) * 2) / 3;
  }
  let t = (JPLL[face] ?? 0) * nr + x - y;
  if (t < 0) t += 8;
  if (t >= 8) t -= 8;
  const ra = nr < 1e-15 ? 0 : (0.25 * Math.PI * t) / nr;
  return { ra, dec: Math.asin(Math.max(-1, Math.min(1, z))) };
}

// A point of a tile, (u, v) in [0, 1] along ix and iy: J2000, RA in hours.
export function tileToSky(tile: Tile, u: number, v: number): Sky {
  const n = 2 ** tile.order;
  const p = faceToSky(tile.face, (tile.ix + u) / n, (tile.iy + v) / n);
  return { ra: p.ra / HOUR, dec: p.dec / RAD };
}

// The tile of an order holding a sky point (healpix_base's loc2xyf).
export function skyToTile(order: number, sky: Sky): Tile {
  const n = 2 ** order;
  const z = Math.sin(sky.dec * RAD);
  const za = Math.abs(z);
  const tt = ((((sky.ra * HOUR) / (Math.PI / 2)) % 4) + 4) % 4;
  if (za <= 2 / 3) {
    const t1 = n * (0.5 + tt);
    const t2 = n * z * 0.75;
    const jp = Math.floor(t1 - t2);
    const jm = Math.floor(t1 + t2);
    const ifp = Math.floor(jp / n);
    const ifm = Math.floor(jm / n);
    const face = ifp === ifm ? ifp | 4 : ifp < ifm ? ifp : ifm + 8;
    return { order, face, ix: jm % n, iy: n - (jp % n) - 1 };
  }
  const ntt = Math.min(3, Math.floor(tt));
  const tp = tt - ntt;
  const tmp = n * Math.sqrt(3 * (1 - za));
  const jp = Math.min(n - 1, Math.floor(tp * tmp));
  const jm = Math.min(n - 1, Math.floor((1 - tp) * tmp));
  return z >= 0
    ? { order, face: ntt, ix: n - jm - 1, iy: n - jp - 1 }
    : { order, face: ntt + 8, ix: jp, iy: jm };
}

// Bits of v spread to the even places: 0b101 → 0b10001.
function spread(v: number): number {
  let out = 0;
  for (let bit = 1, place = 1; bit <= v; bit *= 2, place *= 4) if (Math.floor(v / bit) % 2) out += place;
  return out;
}

// The nested pixel number, the tile's file name.
export function tileIndex(tile: Tile): number {
  return tile.face * 4 ** tile.order + spread(tile.ix) + 2 * spread(tile.iy);
}

export function tileKey(tile: Tile): string {
  return `${tile.order}/${tileIndex(tile)}`;
}

export function tilePath(tile: Tile): string {
  const n = tileIndex(tile);
  return `Norder${tile.order}/Dir${Math.floor(n / 10000) * 10000}/Npix${n}.jpg`;
}

export function parent(tile: Tile): Tile | null {
  if (tile.order === 0) return null;
  return { order: tile.order - 1, face: tile.face, ix: Math.floor(tile.ix / 2), iy: Math.floor(tile.iy / 2) };
}

export function children(tile: Tile): Tile[] {
  const { order, face, ix, iy } = tile;
  return [
    { order: order + 1, face, ix: 2 * ix, iy: 2 * iy },
    { order: order + 1, face, ix: 2 * ix + 1, iy: 2 * iy },
    { order: order + 1, face, ix: 2 * ix, iy: 2 * iy + 1 },
    { order: order + 1, face, ix: 2 * ix + 1, iy: 2 * iy + 1 },
  ];
}

// Degrees from a tile's centre to its farthest corner or edge, with a margin for
// the edges' curve.
function tileRadius(tile: Tile, center: Sky): number {
  let r = 0;
  for (const [u, v] of [
    [0, 0],
    [1, 0],
    [0, 1],
    [1, 1],
    [0.5, 0],
    [0, 0.5],
    [1, 0.5],
    [0.5, 1],
  ] as const) {
    r = Math.max(r, separation(center, tileToSky(tile, u, v)));
  }
  return r * 1.1;
}

// The tiles of an order within `radius` degrees of a point: down from the 12
// faces, keeping a tile while its centre is closer than the radius plus its own.
export function tilesInDisc(order: number, center: Sky, radius: number): Tile[] {
  let level: Tile[] = [];
  for (let face = 0; face < 12; face++) level.push({ order: 0, face, ix: 0, iy: 0 });
  for (let o = 0; ; o++) {
    level = level.filter((tile) => {
      const middle = tileToSky(tile, 0.5, 0.5);
      return separation(middle, center) < radius + tileRadius(tile, middle);
    });
    if (o >= order) return level;
    level = level.flatMap(children);
  }
}

// Radians across one pixel of a tile of this order (512 px tiles).
function pixelSize(order: number): number {
  return Math.sqrt((4 * Math.PI) / (12 * 4 ** (order + 9)));
}

// The coarsest order whose pixels are as fine as the screen's (at most 2 device
// pixels per CSS pixel), within the survey's deepest.
export function tileOrder(view: View, pixelRatio: number, deepest: number): number {
  const screen = 1 / (view.scale * Math.min(2, pixelRatio || 1));
  for (let order = 0; order < deepest; order++) if (pixelSize(order) <= screen) return order;
  return deepest;
}

export function tilesInView(view: View, order: number): Tile[] {
  return tilesInDisc(order, view.center, viewRadius(view));
}

// The tiles around a view, with a margin: kept while the view pans and zooms
// within it at the same order, so a drag does not walk the tiles down from the
// 12 faces at every step (and the tiles just past the edge come early).
export type Cover = { order: number; center: Sky; radius: number; tiles: Tile[] };

export const COVER_MARGIN = 1.3;

export function coverView(view: View, order: number, previous: Cover | null): Cover {
  const radius = viewRadius(view);
  if (previous && previous.order === order && separation(previous.center, view.center) + radius <= previous.radius) {
    return previous;
  }
  const wide = radius * COVER_MARGIN;
  return { order, center: { ...view.center }, radius: wide, tiles: tilesInDisc(order, view.center, wide) };
}

// -- Drawing ----------------------------------------------------------------------

// Cells a tile is cut into across: each is drawn as a parallelogram, so large
// (low order) tiles need more to follow the sky's curve.
function cells(order: number): number {
  return order < 4 ? 16 : 8;
}

// The tile's grid of points on screen, (cells + 1)², null where the
// projection does not reach (behind the view).
export function tileGrid(view: View, tile: Tile): (Point | null)[][] {
  const n = cells(tile.order);
  const grid: (Point | null)[][] = [];
  for (let i = 0; i <= n; i++) {
    const row: (Point | null)[] = [];
    for (let j = 0; j <= n; j++) row.push(project(view, tileToSky(tile, i / n, j / n)));
    grid.push(row);
  }
  return grid;
}

// A tile's image onto the view. The image's columns run along iy and its rows
// along ix: its top-left pixel is the tile's south corner. Each cell is one
// affine map from three of its corners, with no clipping (a clip's antialiased
// edge shows as a seam); its source rectangle, grown by a pixel, covers the
// cracks between cells, and at the tile's edge (where there is no pixel beyond)
// its last pixel is stretched one further, over the crack to the next tile.
export function drawTile(context: CanvasRenderingContext2D, view: View, tile: Tile, image: CanvasImageSource & { width: number; height: number }): void {
  const grid = tileGrid(view, tile);
  const n = grid.length - 1;
  const w = image.width;
  const h = image.height;
  const cw = w / n;
  const ch = h / n;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const p00 = grid[i]?.[j];
      const p10 = grid[i + 1]?.[j];
      const p01 = grid[i]?.[j + 1];
      const p11 = grid[i + 1]?.[j + 1];
      if (!p00 || !p10 || !p01 || !p11) continue;
      const xs = [p00.x, p10.x, p01.x, p11.x];
      const ys = [p00.y, p10.y, p01.y, p11.y];
      if (Math.max(...xs) < 0 || Math.min(...xs) > view.width) continue;
      if (Math.max(...ys) < 0 || Math.min(...ys) > view.height) continue;
      context.save();
      // Image x (a column, along iy) runs p00 → p01; image y (a row, along ix) p00 → p10.
      context.transform((p01.x - p00.x) / cw, (p01.y - p00.y) / cw, (p10.x - p00.x) / ch, (p10.y - p00.y) / ch, p00.x, p00.y);
      const sx = Math.max(0, j * cw - 1);
      const sy = Math.max(0, i * ch - 1);
      const sw = Math.min(w, (j + 1) * cw + 1) - sx;
      const sh = Math.min(h, (i + 1) * ch + 1) - sy;
      const left = j === 0 ? 1 : 0;
      const top = i === 0 ? 1 : 0;
      const right = j === n - 1 ? 1 : 0;
      const bottom = i === n - 1 ? 1 : 0;
      context.drawImage(image, sx, sy, sw, sh, sx - j * cw - left, sy - i * ch - top, sw + left + right, sh + top + bottom);
      context.restore();
    }
  }
}
