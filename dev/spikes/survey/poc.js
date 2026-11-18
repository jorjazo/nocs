// Survey image sources side by side, each drawn into the same gnomonic view
// (north up, east left, like NOCS's framing chart), with the time it took.

import { tileToSky, tilesInDisc, nestIndex } from "./healpix.js";

const RAD = Math.PI / 180;
const W = 400;
const H = 300;

const TARGETS = {
  "NGC 2070 (Tarantula)": [84.676, -69.1],
  "M 42": [83.822, -5.391],
  "NGC 3372 (Eta Car)": [161.265, -59.867],
  "NGC 253": [11.888, -25.288],
  "47 Tuc": [6.024, -72.081],
  "M 31": [10.685, 41.269],
  "M 51": [202.47, 47.195],
};

// -- The view ---------------------------------------------------------------------

function makeView(raDeg, decDeg, fovDeg) {
  const ra0 = raDeg * RAD;
  const dec0 = decDeg * RAD;
  const scale = W / (fovDeg * RAD); // px per radian on the tangent plane
  const sd0 = Math.sin(dec0);
  const cd0 = Math.cos(dec0);
  return {
    ra: raDeg,
    dec: decDeg,
    fov: fovDeg,
    scale,
    center: { ra: ra0, dec: dec0 },
    project(p) {
      const cd = Math.cos(p.dec);
      const cosc = sd0 * Math.sin(p.dec) + cd0 * cd * Math.cos(p.ra - ra0);
      if (cosc <= 0.05) return null;
      const xi = (cd * Math.sin(p.ra - ra0)) / cosc;
      const eta = (cd0 * Math.sin(p.dec) - sd0 * cd * Math.cos(p.ra - ra0)) / cosc;
      return { x: W / 2 - xi * scale, y: H / 2 - eta * scale };
    },
  };
}

// -- Panels -----------------------------------------------------------------------

function panel(title) {
  const fig = document.createElement("figure");
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const cap = document.createElement("figcaption");
  cap.innerHTML = `<b>${title}</b><br><span class="wait">asking…</span>`;
  fig.append(canvas, cap);
  document.getElementById("panels").append(fig);
  const status = cap.querySelector("span");
  return {
    ctx: canvas.getContext("2d"),
    say(text, kind = "ok") {
      status.className = kind;
      status.textContent = text;
    },
  };
}

function overlay(ctx) {
  if (!document.getElementById("cross").checked) return;
  ctx.strokeStyle = "#0f0";
  ctx.beginPath();
  ctx.moveTo(W / 2 - 15, H / 2);
  ctx.lineTo(W / 2 + 15, H / 2);
  ctx.moveTo(W / 2, H / 2 - 15);
  ctx.lineTo(W / 2, H / 2 + 15);
  ctx.stroke();
  ctx.fillStyle = "#0f0";
  ctx.fillText("N ↑  E ←", 6, 14);
}

const ms = (t0) => `${Math.round(performance.now() - t0)} ms`;

function loadImage(url, cors = true, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    if (cors) img.crossOrigin = "anonymous";
    const timer = setTimeout(() => {
      img.src = "";
      reject(new Error("timeout"));
    }, timeout);
    img.onload = () => {
      clearTimeout(timer);
      resolve(img);
    };
    img.onerror = () => {
      clearTimeout(timer);
      reject(new Error("error"));
    };
    img.src = url;
  });
}

// An image that already is the view (a cutout service's own TAN projection).
async function cutout(title, url, note = "") {
  const p = panel(title);
  const t0 = performance.now();
  try {
    const img = await loadImage(url, false);
    p.ctx.drawImage(img, 0, 0, W, H);
    overlay(p.ctx);
    p.say(`${ms(t0)} · ${img.naturalWidth}×${img.naturalHeight}${note ? " · " + note : ""}`);
  } catch (e) {
    p.say(`${e.message} after ${ms(t0)}${note ? " · " + note : ""}`, "bad");
  }
}

// -- HiPS, drawn here from its tiles --------------------------------------------------

// A tile's image pixel (column, row) runs along (iy, ix): its (0, 0) corner is the
// tile's south corner, its last column the west one, its last row the east one.
function drawTile(ctx, view, tile, img) {
  const n = tile.order < 4 ? 16 : 8;
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  const grid = [];
  for (let i = 0; i <= n; i++) {
    grid.push([]);
    for (let j = 0; j <= n; j++) grid[i].push(view.project(tileToSky(tile, i / n, j / n)));
  }
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const p00 = grid[i][j];
      const p10 = grid[i + 1][j];
      const p01 = grid[i][j + 1];
      const p11 = grid[i + 1][j + 1];
      if (!p00 || !p10 || !p01 || !p11) continue;
      const xs = [p00.x, p10.x, p01.x, p11.x];
      const ys = [p00.y, p10.y, p01.y, p11.y];
      if (Math.max(...xs) < 0 || Math.min(...xs) > W || Math.max(...ys) < 0 || Math.min(...ys) > H) continue;
      // image (col, row) = (v·w, u·h), u along ix and v along iy. The cell is
      // small enough to be a parallelogram: one affine map from three corners,
      // no clipping (clip edges antialias into seams); its source rectangle
      // grown by a pixel covers the cracks between cells.
      const cw = w / n;
      const ch = h / n;
      ctx.save();
      // image x (column, along v) → p00→p01; image y (row, along u) → p00→p10
      ctx.transform(
        (p01.x - p00.x) / cw,
        (p01.y - p00.y) / cw,
        (p10.x - p00.x) / ch,
        (p10.y - p00.y) / ch,
        p00.x,
        p00.y,
      );
      const sx = Math.max(0, j * cw - 1);
      const sy = Math.max(0, i * ch - 1);
      const sw = Math.min(w, (j + 1) * cw + 1) - sx;
      const sh = Math.min(h, (i + 1) * ch + 1) - sy;
      ctx.drawImage(img, sx, sy, sw, sh, sx - j * cw, sy - i * ch, sw, sh);
      ctx.restore();
    }
  }
}

// The order whose tile pixels are as fine as the view's, within the survey's.
function tileOrder(view, maxOrder, minOrder = 0, tileWidth = 512) {
  const radPerPx = 1 / view.scale;
  const bits = Math.log2(tileWidth);
  for (let k = minOrder; k <= maxOrder; k++) {
    const pix = Math.sqrt((4 * Math.PI) / (12 * 4 ** (k + bits)));
    if (pix <= radPerPx) return k;
  }
  return maxOrder;
}

async function hips(title, base, maxOrder, view, ext = "jpg") {
  const p = panel(title);
  const t0 = performance.now();
  const order = tileOrder(view, maxOrder);
  const radius = Math.hypot(W, H) / 2 / view.scale;
  const tiles = tilesInDisc(order, view.center, radius * 1.05);
  let done = 0;
  let failed = 0;
  let first = null;
  p.say(`order ${order}, ${tiles.length} tiles…`, "wait");
  await Promise.all(
    tiles.map(async (t) => {
      const n = nestIndex(order, t.face, t.ix, t.iy);
      const url = `${base}/Norder${order}/Dir${Math.floor(n / 10000) * 10000}/Npix${n}.${ext}`;
      try {
        const img = await loadImage(url);
        first ??= ms(t0);
        drawTile(p.ctx, view, t, img);
        done++;
      } catch {
        failed++;
      }
    }),
  );
  overlay(p.ctx);
  p.say(
    `${ms(t0)} (first tile ${first ?? "–"}) · order ${order} · ${done}/${tiles.length} tiles${failed ? ` · ${failed} failed` : ""}`,
    failed === tiles.length ? "bad" : "ok",
  );
}

// -- SkyMapper: one exposure per band, at most 0.17°, stacked here into colour ----------

async function skymapper(view) {
  const p = panel("SkyMapper DR4 (g r i → B G R, per-exposure cutouts)");
  const t0 = performance.now();
  const size = Math.min(0.17, view.fov);
  if (view.fov > 0.17) p.say(`only ${size}° of the ${view.fov}° asked (service limit)`, "wait");
  try {
    const q = `https://api.skymapper.nci.org.au/public/siap/dr4/query?POS=${view.ra},${view.dec}&SIZE=${size}&BAND=g,r,i&RESPONSEFORMAT=CSV&VERB=3`;
    const text = await (await fetch(q)).text();
    const [head, ...rows] = text.trim().split("\n");
    if (!rows.length) throw new Error("no images here (north of ~+2°?)");
    const cols = head.split(",");
    const parse = (line) => {
      // quoted fields may hold commas
      const out = [];
      let cur = "";
      let q2 = false;
      for (const ch of line) {
        if (ch === '"') q2 = !q2;
        else if (ch === "," && !q2) {
          out.push(cur);
          cur = "";
        } else cur += ch;
      }
      out.push(cur);
      return Object.fromEntries(cols.map((c, i) => [c, out[i]]));
    };
    const all = rows.map(parse);
    // A full-size exposure per band, preferring one triplet of the same night and CCD.
    const pick = {};
    for (const band of ["g", "r", "i"]) {
      const full = all
        .filter((r) => r.band === band)
        .sort((a, b) => JSON.parse(b.size)[0] * JSON.parse(b.size)[1] - JSON.parse(a.size)[0] * JSON.parse(a.size)[1]);
      pick[band] = full[0];
    }
    if (!pick.g || !pick.r || !pick.i) throw new Error("not all of g, r, i here");
    const imgs = await Promise.all(["i", "r", "g"].map((b) => loadImage(pick[b].preview)));
    const tmp = document.createElement("canvas");
    const side = Math.round((size / view.fov) * W);
    tmp.width = side;
    tmp.height = side;
    const tctx = tmp.getContext("2d", { willReadFrequently: true });
    const planes = imgs.map((img) => {
      tctx.clearRect(0, 0, side, side);
      tctx.drawImage(img, 0, 0, side, side);
      return tctx.getImageData(0, 0, side, side).data;
    });
    const out = tctx.createImageData(side, side);
    for (let k = 0; k < out.data.length; k += 4) {
      out.data[k] = planes[0][k];
      out.data[k + 1] = planes[1][k];
      out.data[k + 2] = planes[2][k];
      out.data[k + 3] = 255;
    }
    tctx.putImageData(out, 0, 0);
    // The PNGs come north up, east left (their CD matrix is nearly diagonal).
    p.ctx.drawImage(tmp, (W - side) / 2, (H - side) / 2);
    overlay(p.ctx);
    p.say(
      `${ms(t0)} · ${size}° · ${["g", "r", "i"].map((b) => pick[b].image_name.split("_")[2]).join(" / ")}`,
      view.fov > 0.17 ? "wait" : "ok",
    );
  } catch (e) {
    p.say(`${e.message} after ${ms(t0)}`, "bad");
  }
}

// -- Pan-STARRS: colour JPEG from fitscut, at most a few arcminutes ----------------------

async function panstarrs(view) {
  const p = panel("Pan-STARRS DR2 fitscut (i r g, dec > −30°)");
  const t0 = performance.now();
  try {
    const list = await (
      await fetch(`https://ps1images.stsci.edu/cgi-bin/ps1filenames.py?ra=${view.ra}&dec=${view.dec}&filters=gri`)
    ).text();
    const files = Object.fromEntries(
      list
        .trim()
        .split("\n")
        .slice(1)
        .map((l) => l.split(/\s+/))
        .map((c) => [c[4], c[7]]),
    );
    if (!files.g || !files.r || !files.i) throw new Error("outside PS1 (dec < −30°)");
    const native = Math.round((view.fov * 3600) / 0.25);
    const size = Math.min(native, 6000);
    const url =
      `https://ps1images.stsci.edu/cgi-bin/fitscut.cgi?red=${files.i}&green=${files.r}&blue=${files.g}` +
      `&ra=${view.ra}&dec=${view.dec}&size=${size}&output_size=${W}&format=jpg&autoscale=99.5`;
    const img = await loadImage(url, false, 40000);
    const drawn = (size / native) * W;
    p.ctx.drawImage(img, (W - drawn) / 2, (H - drawn) / 2, drawn, drawn);
    overlay(p.ctx);
    p.say(`${ms(t0)}${size < native ? ` · only ${((size * 0.25) / 3600).toFixed(2)}° (6000 px cap)` : ""}`);
  } catch (e) {
    p.say(`${e.message} after ${ms(t0)}`, "bad");
  }
}

// -- All of them --------------------------------------------------------------------

function draw() {
  document.getElementById("panels").replaceChildren();
  const ra = Number(document.getElementById("ra").value);
  const dec = Number(document.getElementById("dec").value);
  const fov = Number(document.getElementById("fov").value);
  const view = makeView(ra, dec, fov);
  const h = (fov * H) / W;

  hips("HiPS DSS2 colour @ IRSA (drawn here)", "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color", 9, view);
  hips("HiPS DSS2 colour @ ESA (drawn here)", "https://skies.esac.esa.int/DSSColor", 9, view);
  hips("HiPS 2MASS colour @ ESA (drawn here)", "https://skies.esac.esa.int/2MASSColor", 9, view);
  cutout(
    "CDS hips2fits DSS2 colour (today's first)",
    `https://alasky.cds.unistra.fr/hips-image-services/hips2fits?hips=CDS/P/DSS2/color&width=${W}&height=${H}&fov=${fov}&projection=TAN&coordsys=icrs&ra=${ra}&dec=${dec}&format=jpg`,
  );
  cutout(
    "NASA SkyView DSS2 Red (today's fallback)",
    `https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?Survey=DSS2+Red&Position=${ra},${dec}&Size=${fov},${h}&Pixels=${W},${H}&Projection=Tan&Coordinates=J2000&Return=JPEG`,
  );
  cutout(
    "Legacy Surveys DR10 cutout (colour)",
    `https://www.legacysurvey.org/viewer/jpeg-cutout?ra=${ra}&dec=${dec}&layer=ls-dr10&pixscale=${((fov * 3600) / W).toFixed(3)}&width=${W}&height=${H}`,
  );
  skymapper(view);
  panstarrs(view);
}

const select = document.getElementById("target");
for (const name of Object.keys(TARGETS)) select.add(new Option(name, name));
const fill = () => {
  const [ra, dec] = TARGETS[select.value];
  document.getElementById("ra").value = ra;
  document.getElementById("dec").value = dec;
};
select.onchange = () => {
  fill();
  draw();
};
document.getElementById("form").onsubmit = (e) => {
  e.preventDefault();
  draw();
};
const params = new URLSearchParams(location.search);
if (params.has("t")) select.value = params.get("t");
fill();
if (params.has("fov")) document.getElementById("fov").value = params.get("fov");
if (params.has("cross")) document.getElementById("cross").checked = true;
draw();
