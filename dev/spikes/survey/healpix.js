// HEALPix (nested) just enough to draw HiPS tiles: a point on a tile's face to
// the sky, and the tiles that touch a disc. After healpix_base.cc (xyf2loc).

const JRLL = [2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4];
const JPLL = [1, 3, 5, 7, 0, 2, 4, 6, 1, 3, 5, 7];

// (x, y) in [0, 1] across a base face (x along the nested ix bits, y along iy):
// right ascension and declination in radians.
export function faceToSky(face, x, y) {
  const jr = JRLL[face] - x - y;
  let nr;
  let z;
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
  let t = JPLL[face] * nr + x - y;
  if (t < 0) t += 8;
  if (t >= 8) t -= 8;
  const phi = nr < 1e-15 ? 0 : (0.25 * Math.PI * t) / nr;
  return { ra: phi, dec: Math.asin(Math.max(-1, Math.min(1, z))) };
}

// A tile: order, face and its (ix, iy) on the face; its nested index.
function spread(v) {
  let r = 0n;
  let b = 0n;
  let n = BigInt(v);
  while (n > 0n) {
    r |= (n & 1n) << (2n * b);
    n >>= 1n;
    b += 1n;
  }
  return r;
}

export function nestIndex(order, face, ix, iy) {
  const o = BigInt(order);
  return Number((BigInt(face) << (2n * o)) | spread(ix) | (spread(iy) << 1n));
}

// A point inside a tile, (u, v) in [0, 1] along ix and iy.
export function tileToSky(t, u, v) {
  const n = 2 ** t.order;
  return faceToSky(t.face, (t.ix + u) / n, (t.iy + v) / n);
}

export function separation(a, b) {
  const s =
    Math.sin(a.dec) * Math.sin(b.dec) + Math.cos(a.dec) * Math.cos(b.dec) * Math.cos(a.ra - b.ra);
  return Math.acos(Math.max(-1, Math.min(1, s)));
}

// The tiles of an order within `radius` (radians) of `center`: down from the 12
// faces, keeping a tile when its centre is closer than the radius plus its own.
export function tilesInDisc(order, center, radius) {
  let level = [];
  for (let face = 0; face < 12; face++) level.push({ order: 0, face, ix: 0, iy: 0 });
  for (let o = 0; ; o++) {
    level = level.filter((t) => {
      const c = tileToSky(t, 0.5, 0.5);
      let r = 0;
      for (const [u, v] of [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0], [0, 0.5], [1, 0.5], [0.5, 1]]) {
        r = Math.max(r, separation(c, tileToSky(t, u, v)));
      }
      return separation(c, center) < radius + r * 1.1;
    });
    if (o === order) return level;
    level = level.flatMap((t) =>
      [0, 1].flatMap((dx) =>
        [0, 1].map((dy) => ({ order: o + 1, face: t.face, ix: 2 * t.ix + dx, iy: 2 * t.iy + dy })),
      ),
    );
  }
}
