import assert from "node:assert/strict";
import { test } from "node:test";
import { children, coverView, parent, skyToTile, tileIndex, tileKey, tileOrder, tilePath, tileToSky, tilesInDisc, tilesInView } from "./hips.ts";
import { project, separation, unproject } from "./projection.ts";

const RAD = Math.PI / 180;

// A view `degrees` across its width.
function view(ra: number, dec: number, degrees: number, width = 800, height = 600) {
  return { center: { ra, dec }, scale: width / (degrees * RAD), width, height };
}

// Points spread over the whole sky, the poles included.
function* sky(count: number) {
  for (let i = 0; i < count; i++) {
    const dec = Math.asin(-1 + (2 * (i + 0.5)) / count) / RAD;
    yield { ra: (i * 0.618034 * 24) % 24, dec };
  }
}

test("a tile's centre falls in that tile, all over the sky and at every order", () => {
  for (const order of [0, 1, 3, 6, 9]) {
    for (const point of sky(2000)) {
      const tile = skyToTile(order, point);
      assert.ok(tile.face >= 0 && tile.face < 12);
      assert.ok(tile.ix >= 0 && tile.ix < 2 ** order && tile.iy >= 0 && tile.iy < 2 ** order);
      assert.deepEqual(skyToTile(order, tileToSky(tile, 0.5, 0.5)), tile);
    }
  }
});

test("known HEALPix places: face centres and the poles", () => {
  // Face 4 is centred on RA 0, Dec 0; face 0's north corner is the pole.
  assert.deepEqual(skyToTile(0, { ra: 0.01, dec: 0 }).face, 4);
  const pole = tileToSky({ order: 0, face: 0, ix: 0, iy: 0 }, 1, 1);
  assert.ok(Math.abs(pole.dec - 90) < 1e-9);
  const south = tileToSky({ order: 0, face: 8, ix: 0, iy: 0 }, 0, 0);
  assert.ok(Math.abs(south.dec + 90) < 1e-9);
  // Face 5 is centred on RA 6 h.
  const middle = tileToSky({ order: 0, face: 5, ix: 0, iy: 0 }, 0.5, 0.5);
  assert.ok(Math.abs(middle.ra - 6) < 1e-9 && Math.abs(middle.dec) < 1e-9);
});

test("nested numbers and file names", () => {
  assert.equal(tileIndex({ order: 0, face: 11, ix: 0, iy: 0 }), 11);
  // ix in the even bits, iy in the odd ones.
  assert.equal(tileIndex({ order: 2, face: 1, ix: 3, iy: 0 }), 16 + 0b0101);
  assert.equal(tileIndex({ order: 2, face: 1, ix: 0, iy: 3 }), 16 + 0b1010);
  assert.equal(tileIndex({ order: 9, face: 11, ix: 511, iy: 511 }), 12 * 4 ** 9 - 1);
  assert.equal(tilePath({ order: 3, face: 4, ix: 5, iy: 2 }), "Norder3/Dir0/Npix" + (4 * 64 + 0b011001) + ".jpg");
  const deep = { order: 9, face: 4, ix: 300, iy: 77 };
  const n = tileIndex(deep);
  assert.equal(tilePath(deep), `Norder9/Dir${Math.floor(n / 10000) * 10000}/Npix${n}.jpg`);
  assert.equal(tileKey(deep), `9/${n}`);
});

test("a tile's parent holds it", () => {
  for (const point of sky(300)) {
    const tile = skyToTile(7, point);
    assert.deepEqual(parent(tile), skyToTile(6, tileToSky(tile, 0.5, 0.5)));
  }
  assert.equal(parent({ order: 0, face: 3, ix: 0, iy: 0 }), null);
});

test("the tiles of a view cover all of it", () => {
  const cases = [
    view(5.6, -69, 1),
    view(5.6, -69, 5),
    view(10.7, -59.9, 40),
    view(0.05, 0, 2), // across RA 0
    view(2, 89.5, 3), // at the pole
    view(18, -89.7, 3, 400, 800),
  ];
  for (const v of cases) {
    const order = tileOrder(v, 1, 9);
    const tiles = new Set(tilesInView(v, order).map(tileKey));
    for (let x = 0; x <= v.width; x += v.width / 20) {
      for (let y = 0; y <= v.height; y += v.height / 20) {
        const point = unproject(v, { x, y });
        assert.ok(tiles.has(tileKey(skyToTile(order, point))), `${JSON.stringify(v.center)} at ${x},${y}`);
      }
    }
    // And not much more: a few tiles past the view's edge, not the sky.
    assert.ok(tiles.size < 60, `${tiles.size} tiles`);
  }
});

test("the order follows the screen's pixels, so a view needs about as many tiles whatever its field", () => {
  for (const degrees of [0.3, 1, 5, 20, 60]) {
    const v = view(5.6, -30, degrees);
    const order = tileOrder(v, 1, 9);
    const count = tilesInView(v, order).length;
    assert.ok(count >= 2 && count <= 40, `${degrees}°: ${count} tiles at order ${order}`);
  }
  // Finer for a sharper screen, never past the survey's deepest.
  assert.equal(tileOrder(view(1, 0, 1), 2, 9), tileOrder(view(1, 0, 1), 1, 9) + 1);
  assert.equal(tileOrder(view(1, 0, 0.01), 2, 9), 9);
});

test("a disc's tiles are near it", () => {
  const center = { ra: 12, dec: 30 };
  for (const tile of tilesInDisc(6, center, 2)) {
    assert.ok(separation(center, tileToSky(tile, 0.5, 0.5)) < 4);
  }
});

test("a tile drawn by its corners lands where its sky is", () => {
  // The middle of a tile, projected, is inside the quadrilateral of its corners.
  const v = view(5.6, -69, 2);
  const tile = tilesInView(v, tileOrder(v, 1, 9))[0];
  assert.ok(tile);
  const middle = project(v, tileToSky(tile, 0.5, 0.5));
  const corners = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ].map(([u = 0, w = 0]) => project(v, tileToSky(tile, u, w)));
  assert.ok(middle && corners.every(Boolean));
  const xs = corners.map((c) => c?.x ?? 0);
  const ys = corners.map((c) => c?.y ?? 0);
  assert.ok(middle.x > Math.min(...xs) && middle.x < Math.max(...xs));
  assert.ok(middle.y > Math.min(...ys) && middle.y < Math.max(...ys));
});

test("a tile's children split it in four", () => {
  const tile = skyToTile(5, { ra: 3, dec: -40 });
  const kids = children(tile);
  assert.equal(new Set(kids.map(tileKey)).size, 4);
  for (const kid of kids) assert.deepEqual(parent(kid), tile);
});

test("a view's cover is kept while the view stays inside its margin", () => {
  const v = view(5.6, -69, 2);
  const order = tileOrder(v, 1, 9);
  const cover = coverView(v, order, null);
  // A short pan: the same tiles, not walked down again.
  const panned = { ...v, center: { ra: 5.61, dec: -69.05 } };
  assert.equal(coverView(panned, order, cover), cover);
  // Past the margin, or at another order: a new one, which covers the view.
  const far = { ...v, center: { ra: 5.9, dec: -69.5 } };
  const moved = coverView(far, order, cover);
  assert.ok(moved !== cover);
  assert.ok(coverView(v, order + 1, cover) !== cover);
  const keys = new Set(moved.tiles.map(tileKey));
  for (let x = 0; x <= far.width; x += far.width / 10) {
    for (let y = 0; y <= far.height; y += far.height / 10) {
      assert.ok(keys.has(tileKey(skyToTile(order, unproject(far, { x, y })))));
    }
  }
  // Whatever kept cover a view passes, it still covers that view.
  for (const pan of [0, 0.02, 0.05, 0.1]) {
    const p = { ...v, center: { ra: 5.6 + pan, dec: -69 } };
    const kept = new Set(coverView(p, order, cover).tiles.map(tileKey));
    for (let x = 0; x <= p.width; x += p.width / 10) {
      for (let y = 0; y <= p.height; y += p.height / 10) {
        assert.ok(kept.has(tileKey(skyToTile(order, unproject(p, { x, y })))), `pan ${pan} at ${x},${y}`);
      }
    }
  }
});
