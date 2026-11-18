# Survey image sources while CDS is down

Outcome: the framing chart now draws the DSS2 colour HiPS itself, from IRSA, ESA
or CDS (`web/src/lib/sky/hips.ts`, `survey.ts`), with SkyView as the last resort.

Measured 2026-11-18 from the maintainer's network in Chile, with CDS down after a
cyberattack: `alasky.cds.unistra.fr` answers every request (hips2fits included) with
a 404 "Page unavailable" page, and ESASky's own site is "temporarily unavailable".
The POC is `dev/spikes/survey/` (a static page: `python3 -m http.server -d
dev/spikes/survey 8091`). It draws every source into the same 400×300 gnomonic
view, north up and east left like the framing chart, and times it.

## What each source gives

| Source | Colour | Field | Coverage | CORS | Time (400 px) |
|---|---|---|---|---|---|
| HiPS DSS2 colour @ IRSA (tiles drawn in the browser) | yes | any (0.15°–40° tried) | all sky | `*` | 0.5–2.3 s cold, 1.4 s at 40° |
| HiPS DSS2 colour @ ESA `skies.esac.esa.int` | yes | any | all sky | `*` | 0.5–4.3 s cold |
| HiPS 2MASS / AllWISE / SDSS9 colour @ ESA | yes (IR) | any | all sky (SDSS: north) | `*` | ~0.7 s |
| CDS hips2fits (today's first) | yes | any | all sky | `*` | down |
| NASA SkyView DSS2 Red (today's fallback) | no | ≤ 5° in practice | all sky | none | 1.3 s at 0.5°, 12.8 s at 5° |
| Legacy Surveys DR10 `jpeg-cutout` | yes | any | extragalactic sky only | `*` | 1–5.6 s |
| SkyMapper DR4 SIAP cutouts | per band | **≤ 0.17°** | south | `*` | 4.4–6.3 s |
| Pan-STARRS fitscut | yes | ≤ 0.42° (6000 px) | dec > −30° | `*` | 6 s |

- **The DSS2 colour HiPS that hips2fits draws from is mirrored, identical, at IRSA
  (`https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color`) and ESA
  (`https://skies.esac.esa.int/DSSColor`)**: same `properties`, same tile bytes,
  orders 0–9 (512 px JPEG tiles, ~1″ per pixel at order 9), `Norder3/Allsky.jpg`
  too. Both send `Access-Control-Allow-Origin: *`. A tile takes 0.3–1 s
  (IRSA) or 0.9–1.9 s (ESA) cold, 30–100 kB.
- Drawn in the browser the time follows the view's pixels, not its field: the order
  is the first whose tile pixels are as fine as the view's, so a 400×300 view takes
  6–13 tiles at 0.5°–5° and 11 at 40° (order 1). 5° on the LMC: 1–2.3 s, against
  SkyView's 12.8 s. The 5° cap SkyView forced is not needed.
- Drawing: each tile is cut into 8×8 cells (16×16 below order 4), each cell an
  affine map from three of its projected corners, its source rectangle grown by one
  pixel. Clipping to triangles instead left antialiased seams. A tile's image column
  runs along the HEALPix `iy` bits and its row along `ix`: pixel (0, 0) is the
  tile's south corner. Checked against SkyView at NGC 253 (same orientation and
  stars) and at M 42 / the LMC.
- **SkyMapper is not a framing image.** Its cutout service refuses more than 0.17°
  a side ("must be between 0.0 and 0.17 deg"), gives one exposure per band (not
  coadds), grey PNGs stretched each on their own and often from different nights
  and CCDs, cut at CCD edges (454×540 instead of 540×540). A g/r/i stack is
  washed out. SkyMapper's colour HiPS was CDS's, so down with it.
- Legacy Surveys DR10 shows garbage in the Galactic plane and the Magellanic Clouds
  (saturated, partial bricks at NGC 2070) and has no data at M 42; good on
  galaxies (NGC 253).
- Pan-STARRS: nothing south of −30°, fitscut caps at 6000 native pixels (0.42°).
- SkyView's multi-survey `RGB=1` query answered "no data in the selected region";
  not pursued.
