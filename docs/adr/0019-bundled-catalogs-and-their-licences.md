# 0019. Bundled catalogs and their licences

Date: 2026-10-31 · Status: Proposed

## Context

Phase 3 lets the user pick a target from the phone ("NGC 292", "Nebulosa de Orión")
and frame it. In the field the rig has no internet, so the data has to ship with
nocsd: a catalog of deep-sky objects for the search (3.4) and, later, stars for the
offline framing chart (3.7). NOCS is AGPL-3.0 (ADR 0008); data under another licence
can ship beside it if the licence allows redistribution and its terms are kept.

Candidates and facts measured for the deep-sky catalog:

- **OpenNGC** (Mattia Verga, CC BY-SA 4.0): every NGC and IC object with type,
  J2000 position, magnitudes, axes and position angle, Messier numbers and
  cross-identifications (Caldwell, PGC, UGC, ESO, LBN, …), plus an addendum of 64
  bright objects outside NGC/IC (Large Magellanic Cloud, Pleiades, Hyades, Coalsack,
  Melotte and Collinder clusters). Release v20260501: 13 970 rows, 13 371 real
  objects once duplicates and non-existent ones are dropped. Common names for only
  ~130 objects, all English; none in Spanish. Some values are off: NGC 253's visual
  magnitude is 11.1 (its blue one, 7.9, is right).
- Stellarium's DSO catalog and name translations are GPL: usable, but they would mix
  a second copyleft licence into the data for little gain over OpenNGC.
- SIMBAD/NED have the best data but are online services with their own terms.

## Decision

### Deep-sky objects: OpenNGC, built by a pinned script

- `dev/catalog/build.py` downloads one OpenNGC release, pinned by version **and
  SHA-256**, and writes `server/src/nocs/targets/data/openngc.json.gz` and the
  licence text beside it. Both are committed; neither the build nor nocsd downloads
  anything at run time. The output is byte for byte reproducible (gzip without a
  timestamp), so a rebuild shows up in review only when the data changes.
- The file is gzipped JSON, one row per object: id, type, RA (hours) and Dec
  (degrees) J2000, constellation, magnitude, major and minor axes, position angle,
  aliases, English names, Spanish names. Duplicate rows become aliases of the object
  they repeat (IC 11 → NGC 281, M 102 → M 101 as OpenNGC reads it). Only
  cross-identifications people search by are kept (Messier, Caldwell, Melotte,
  Collinder, LBN, PK, PGC, UGC, ESO); 2MASX, SDSS, MCG and IRAS would double the
  file. Magnitude is the brighter of the visual and blue ones.
- NOCS adds common names in `dev/catalog/names.tsv`: English ones OpenNGC lacks
  ("Sculptor Galaxy", "SMC", "Gabriela Mistral Nebula") and Spanish ones where they
  differ ("Pequeña Nube de Magallanes", "Nebulosa de Orión"). The file is licensed
  CC BY-SA 4.0 like the data it is merged into, so the bundled catalog is one work
  under one licence.
- nocsd loads it once, on the first request, in a worker thread, and searches it in
  memory. No SQLite: the data is read-only and small, and matching designations
  written loosely ("m31", "NGC 0292", "Caldwell 65") and names without accents
  needs our own normalisation either way.
- Measured, file 347 kB: loading takes 0.36 s on the lab Pi 5 (0.08 s on a laptop)
  and +22.5 MB of RSS; a search takes ~0.5 ms there, 2 ms at worst (a short id
  prefix such as "ngc 2"), and ~0.12 ms on a laptop.

### Attribution

CC BY-SA asks for credit, a link to the licence and notice of changes wherever the
data is shown. The data file carries its sources (name, version, URL, licence,
attribution) and `GET /api/targets/sources` serves them; the web app's Plan screen
(3.6) and its About page show the attribution. The licence text ships next to the
data in the package. Changes to the data (conversion, names added) stay under
CC BY-SA 4.0 and are published in this repository.

### Stars for the offline chart (3.7): a Tycho-2 subset

The framing chart needs stars to about magnitude 10 around any target. 3.7 will
add a Tycho-2 subset (ESA, distributed by CDS; credit asked, no copyleft), built
the same way: a pinned download checked by SHA-256, a compact committed file, its
source and credit in the same `sources` list. 3.7 checks the terms of the exact
files it uses against rule 1 below, and decides the subset's size and format
(expected a few MB); this ADR only fixes the rules.

### Rules for any bundled catalog

1. Only data whose licence allows redistribution, recorded here before it ships.
2. Built by a script in `dev/` from a pinned, checksummed release; the output and
   its licence committed together.
3. Its source and attribution reach the user through the API, not only the repo.
4. Nothing is downloaded on the Pi at run time. Online imagery for framing (CDS
   hips2fits) is fetched by the browser when the user opts in, never bundled.

## Consequences

- Target search works offline from the first boot and adds ~350 kB to the package
  and ~23 MB of memory once used.
- OpenNGC's own errors ship with it; a fix goes upstream, and the pinned version is
  bumped (with the search tests rerun) when a release brings it.
- The Spanish names are NOCS's own and few (~115 objects); a wrong one is fixed in
  `names.tsv` and the file rebuilt.
- Copyleft data and AGPL code ship side by side as separate works; the data never
  becomes part of the program's source, nor the program of the data.
