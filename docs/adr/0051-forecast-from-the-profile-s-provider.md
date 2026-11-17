# 0051. Tonight's forecast comes from a provider the profile names, fetched by the box

Date: 2026-11-16 · Status: Proposed

## Context

Tonight's weather card showed only the power box's sensor: the temperature, the
humidity and the dew point now. The maintainer wants tonight's forecast beside it
("Experiencia NOCS", the Tonight view): clouds, rain, wind, humidity and temperature,
hour by hour from now until the end of the dark window. Facts:

- **The box is usually offline in the field.** It runs its own hotspot (ADR 0028);
  the phones on it have no internet either. At home, before leaving, the box usually
  has it.
- **A forecast needs a position, and the position is the owner's.** Observers do not
  see where the box is (ADR 0047), and a service on the internet should learn no more
  than it needs: a forecast is the same within ~10 km.
- **Open-Meteo** gives hourly forecasts (cloud cover in total and low, mid and high,
  precipitation and its probability, wind and gusts, humidity, temperature) for free,
  without an account or a key, over HTTPS. Other services (with better cloud models
  for astronomy) need a key; the maintainer may add them later.
- **NOCS has no HTTP client among its dependencies**; Python's `urllib` does the job
  for one request every few hours.

## Decision

- **The profile names the provider**: `forecast.provider` in a profile, `None` (no
  forecast) unless the owner turns it on in the profile editor; `"open-meteo"` is the
  only one. A provider that needs a key will add its own fields then (kept out of the
  state, which observers see).
- **The box fetches it**, for the active site's position rounded to 0.1° (about
  10 km), without its elevation: 3 days of hours from today's midnight UTC, in UTC.
  Every 2 hours; after a failed attempt, every 10 minutes; at once when the provider
  or the rounded position changes.
- **The last forecast is kept on disk** (`<data dir>/forecast.json`), with its
  provider, the rounded position and when it was fetched: one fetched at home serves
  in the field, after a restart too.
- **The state's `forecast`** (None while the active profile asks for none) has the
  provider, when the forecast was fetched, the last attempt and its error, and its
  hours from the current one on while it is less than 48 hours old (none after).
  Observers see it: it does not say where the box is.
- **Tonight's Weather card** shows the sensor's readings with their source, then the
  forecast's hours until the end of the dark window (else of the night), when it was
  fetched and from which provider. Closed, it says the next hour's forecast, else the
  sensor's reading; the dew warning still comes from the sensor.

## Consequences

- With the forecast on, the box makes an HTTPS request to api.open-meteo.com every
  2 hours while online (every 10 minutes while it tries): the owner's choice, said in
  the profile editor.
- A forecast fetched at home a day before still shows in the field, with its age; it
  is not a nowcast, and the cards say when it was fetched.
- Another provider is a function in `nocs.forecast.service.fetch` and a name in
  `ForecastProvider`.
