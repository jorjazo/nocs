# 0020. Framing chart and its star data

Date: 2026-10-31 · Status: Proposed

## Context

Phase 3 frames a target from the phone: where will the camera's frame fall, and how
should it be turned? The rig has no internet in the field, so the chart has to work
offline from data nocsd bundles (ADR 0019, rule 4). The Plan screen (3.6) hosts it.
3.7a builds the offline chart; 3.7b adds online survey imagery, the maintainer's own
solved frames as a background, and a "turn the camera N°" helper.

Facts checked before deciding:

- **Star data and licences.** ADR 0019 expected Tycho-2 to ask only for credit. Its
  CDS ReadMe (I/259, updated 17 August 2026) gives `License: CC-BY-NC-3.0 IGO`, and
  ESA states that "the Hipparcos and Tycho Catalogues are distributed under the CC
  BY-NC 3.0 IGO licence" with the credit "ESA". Gaia's data carry the same licence.
  The alternatives without "non-commercial" are worse: the SAO catalogue (1966,
  photographic magnitudes, incomplete at 9–10) or UCAC4 (~8.5 GB to download, its
  bright stars taken from Tycho-2). Desktop planetariums ship Tycho-2 too.
- **Size.** Tycho-2 and its supplement 1 (the Hipparcos stars missing from it, the
  brightest among them) hold 2 557 501 stars; 357 145 are brighter than V 10. Kept
  to 0.36″ and 0.05 mag, sorted by declination with each column split into byte
  planes, they take 1.41 MB with xz.
- **Speed.** Measured with `dev/catalog/measure_chart.py` (stars and objects around
  a point, turned into the response's JSON). Lab Pi 5: loading 0.155 s from a cold
  cache, +27 MB RSS; a request 1–6 ms up to 4° of radius, 4–9 ms at 10°, 11–19 ms
  at 30°. Laptop: 0.05 s, 0.3–4 ms. Drawing a phone-sized chart (375 × 566 at 2×
  pixels, laptop browser) takes at most 1.5 ms: a drag redraws at 60 FPS.

## Decision

### Stars: a Tycho-2 subset under CC BY-NC 3.0 IGO

- The maintainer accepted the non-commercial licence (2026-10-31): NOCS is free
  software built and used without commercial intent. The restriction binds whoever
  redistributes the data commercially, not NOCS's own code (AGPL, ADR 0008).
- `dev/catalog/build_stars.py` reads the 20 parts of the main catalogue and
  supplement 1 from CDS (or its CfA mirror), checks each file's SHA-256, keeps the
  stars to Johnson V 10 (approximated from BT and VT as the ReadMe gives it; Hp for
  the Hipparcos stars that lack VT, so Sirius reads −1.1), moves supplement 1 from
  J1991.25 to J2000, and writes `server/src/nocs/targets/data/tycho2.bin.xz` and
  `LICENSE-Tycho2.txt` (credit, licence and its URL, what NOCS changed). Both are
  committed; the output is byte for byte reproducible.
- The file is one JSON header line (format, sources, units) and three integer
  columns compressed with xz: declination steps, right ascensions, magnitudes. Proper
  motions are not applied past J2000 (a few arcseconds for nearly every star).
- **The chart works without the file.** nocsd then sends no stars and says so
  (`star_catalog: false`), the chart shows the deep-sky objects alone. A
  distribution that must avoid the non-commercial terms leaves the file out.
- Its source and credit reach the user through `GET /api/targets/sources` and on
  the chart itself ("Stars: Tycho-2, ESA · Objects: OpenNGC").

### Server: one request per view

`GET /api/targets/chart?ra=&dec=&radius=&magnitude=&limit=&objects=` (observers
may use it, like the rest of `/api/targets/`) answers with the stars within
`radius` degrees of a J2000 point down to `magnitude`, brightest first, as
`[ra, dec, mag]` triples (at most `limit`, 5000 by default), and the deep-sky
objects whose extent reaches into the circle (the brightest `objects`, 300 by
default: a 30° view near the Magellanic Clouds holds a thousand), with their axes
and position angle. Stars live in memory as NumPy arrays sorted by declination: a
request takes the declination band and tests the distance on unit vectors. The file
is loaded on the first request, in a worker thread.

### Web: a canvas chart the Plan screen embeds

`SkyChart.svelte` draws on a canvas, in a gnomonic projection centred on the view,
north up and east to the left. The camera's frame stays in the middle and the sky
moves under it, so the chart's centre is where the frame points (a bindable J2000
position for Go and centre). A gnomonic chart is what a sensor sees: the frame is
an exact rectangle of `cameras.<role>.field`'s size, turned by its rotation, the
position angle of its top east of north as a plate solution gives it (ADR 0018).

- Stars sized by magnitude, down to a limit that follows the view (V 10 below 1.5°,
  ~6.9 at 30°); deep-sky objects as ellipses by their axes and position angle
  (dashed for open clusters and dark nebulae), marks for objects too small to
  outline (only those within 3 magnitudes of the stars' limit), labels where they do
  not crowd; a crosshair, a notch for the frame's top, and the centre's J2000
  coordinates in the mono font.
- Drag to pan, pinch or wheel to zoom (0.2° to 70°), double tap to go back to the
  target; arrows, + and − on a keyboard. Night mode draws in its red palette.
- The client asks for a margin around the view (1.6 times its half diagonal) and
  asks again only when the view leaves what it has or needs fainter stars.
- Until 3.6, the chart lives at `#/dev/chart`.

## Consequences

- +1.4 MB in the package and +27 MB of memory on the Pi once a chart is drawn.
- NOCS's packages carry data under a non-commercial licence. A vendor selling
  appliances with NOCS must drop the star file or ask ESA; the package's copyright
  notice (phase 6) has to say so.
- Tycho-2's own limits ship with it: no stars fainter than V ~10 in the chart, and
  Hipparcos magnitudes (Hp) for a few bright stars.
- 3.7b adds the survey background from CDS hips2fits (fetched by the browser,
  opt-in), the user's solved frames, and the rotation helper to this chart.
- Amended in 3.7b (2026-11-01): the browser falls back to NASA SkyView (DSS2 red)
  when CDS does not answer within 12 s; on that day no CDS host answered from the
  maintainer's network, while SkyView made a 400-pixel image in 3 s. Both give a
  gnomonic image, north up and east left, like the chart. The user's own solved
  frames move to a stage of their own (3.7c): they need the solutions kept with
  the saved frames on the server.
- Amended in 3.7c (2026-11-01): the user's own frames come from nocsd, not the
  internet: saved lights solved on request, their solutions kept in the frame
  catalog and a 1024 px JPEG of each in the data directory
  (`GET /api/frames/solved`, owner only). The chart draws them under the stars,
  each on the corners where its solution put it.
- Amended after rc2 (2026-11-12): the survey image says why it is missing and asks
  for what the services can give in time. Measured from the maintainer's network in
  Chile (NGC 2070, DSS2 Red, 4:3, two rounds): SkyView took 2.8–3.9 s for 1°,
  4.5–7.0 s for 2°, 8.8–14.4 s for 4°, 12–13 s for 5° (also at M 31 and M 42),
  18.6 s for 6°, 28–35 s for 7.7° and 41–53 s for 10.4°, whatever the pixels
  (200, 400 or 800 across): its time follows the field's area. CDS could not be
  measured: `alasky` and `alaskybis` (130.79.128.175/179) still drop every
  connection from that network, while `cds.unistra.fr` (130.79.129.14) answers;
  hips2fits draws from HiPS tiles at the order the pixels need, so its time should
  follow the pixels rather than the field. So the image covers at most 5° along the
  view's longer side (its middle, where the frame is: about 12 s, under half of
  SkyView's 30 s), at the view's own pixels up to 800. The service that gave the last
  image is tried first, by every chart and after a reload (kept in the browser);
  a preference for SkyView lasts 20 h, so the next night asks CDS (colour) first
  again. A request on its way is not started over by a small pan or zoom, and a
  failed one is not asked again until the view moves on or the device comes back
  online. When no service gives an image, the chart says why per service, told
  apart in the browser: an `<img>` does not give the HTTP status (SkyView allows no
  CORS), so after a miss a no-cors `fetch` of the host's `/favicon.ico` (5 s)
  tells "too slow" or "answered with an error" (the host answers) from "not
  answering" (no answer in time) and "cannot be reached" (fails at once; all of
  them: "No internet on this device?"); `navigator.onLine` false is "this device is
  offline". SkyView's Mellinger Red (an all-sky mosaic, ~36″ per pixel) answered
  4°, 10.4° and 20° in 3–4 s and could cover a wide view whole; not used: its terms
  of use would need checking first.
