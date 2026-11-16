<script lang="ts">
  // Tonight's weather: the conditions now from the weather role (ADR 0017) and the
  // device that says so, and the forecast hour by hour until the end of the dark
  // window, from the profile's provider (ADR 0051), with when it was fetched.
  // Closed, its header says the next hour's forecast (else the sensor's reading);
  // the dew warning comes from the sensor, open or closed.
  import { formatDecimal, formatDuration, formatTemperature, formatTime } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { forecastHours } from "../lib/tonightcards";
  import type { ForecastHour, ForecastState, WeatherState } from "../lib/types";
  import Section from "./Section.svelte";

  let {
    weather,
    forecast,
    until,
    now,
    open,
    ontoggle,
  }: {
    weather: WeatherState | null;
    forecast: ForecastState | null;
    // The forecast runs until here (ms): the end of the dark window.
    until: number;
    now: number;
    open: boolean;
    ontoggle: (open: boolean) => void;
  } = $props();

  // Below this margin optics start to dew up without heaters.
  const DEW_MARGIN = 3;
  const PROVIDERS: Record<ForecastState["provider"], string> = { "open-meteo": "Open-Meteo" };

  const t = $derived(i18n.t);
  const f = $derived(t.tonight.forecast);
  const locale = $derived(i18n.locale);
  const margin = $derived(
    weather && weather.temperature !== null && weather.dew_point !== null ? weather.temperature - weather.dew_point : null,
  );
  const hours = $derived(forecast ? forecastHours(forecast.hours, now, until) : []);
  const next = $derived(hours[0] ?? null);

  const number = (value: number | null, digits: number) => (value === null ? "—" : formatDecimal(value, locale, digits));
  const percent = (value: number | null) => (value === null ? "—" : `${formatDecimal(value, locale, 0)} %`);
  const temperature = (value: number | null) => (value === null ? "—" : formatTemperature(value, locale, 0));
  const rain = (hour: ForecastHour) => (hour.precipitation === null ? "—" : f.mm(formatDecimal(hour.precipitation, locale, 1)));
  const wind = (hour: ForecastHour) => {
    if (hour.wind_speed === null) return "—";
    const speed = formatDecimal(hour.wind_speed, locale, 0);
    return f.kmh(hour.wind_gusts === null ? speed : `${speed}–${formatDecimal(hour.wind_gusts, locale, 0)}`);
  };

  const summary = $derived.by(() => {
    if (next) return f.nextHour(percent(next.cloud_cover), rain(next), wind(next), percent(next.humidity), temperature(next.temperature));
    if (!weather) return null;
    return [
      weather.temperature === null ? null : formatTemperature(weather.temperature, locale),
      margin === null ? null : t.weather.margin(formatTemperature(margin, locale)),
    ]
      .filter((part) => part !== null)
      .join(" · ");
  });
  const status = $derived(margin !== null && margin < DEW_MARGIN ? { tone: "warning" as const, text: t.weather.dewNearShort } : null);

  const fetchedAgo = $derived(forecast?.fetched ? Math.max(0, (now - Date.parse(forecast.fetched)) / 1000) : null);
  const forecastNote = $derived.by(() => {
    if (!forecast || hours.length > 0) return null;
    if (!forecast.fetched) return f.none;
    if (forecast.hours.length === 0) return f.stale;
    return null;
  });
</script>

<Section scope="tonight" id="weather" title={t.weather.title} {summary} {status} {open} {ontoggle}>
  {#if weather}
    <div class="readouts">
      <div>
        <span class="label muted">{t.weather.temperature}</span>
        <span class="readout">{weather.temperature === null ? "—" : formatTemperature(weather.temperature, locale)}</span>
      </div>
      <div>
        <span class="label muted">{t.weather.humidity}</span>
        <span class="readout">{weather.humidity === null ? "—" : `${formatDecimal(weather.humidity, locale, 0)} %`}</span>
      </div>
      <div>
        <span class="label muted">{t.weather.dewPoint}</span>
        <span class="readout">{weather.dew_point === null ? "—" : formatTemperature(weather.dew_point, locale)}</span>
      </div>
    </div>
    {#if margin !== null}
      <p class="caption" class:warning={margin < DEW_MARGIN}>
        {margin < DEW_MARGIN ? t.weather.dewNear : t.weather.margin(formatTemperature(margin, locale))}
      </p>
    {/if}
    <p class="caption">{t.weather.source(weather.device)}</p>
  {/if}

  {#if forecast}
    <div class="forecast">
      <h3 class="label">{f.title}</h3>
      {#if hours.length > 0}
        <div class="scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{f.hour}</th>
                <th scope="col">{f.clouds}<span class="unit">{f.units.clouds}</span></th>
                <th scope="col">{f.rain}<span class="unit">{f.units.rain}</span></th>
                <th scope="col">{f.wind}<span class="unit">{f.units.wind}</span></th>
                <th scope="col">{f.humidity}<span class="unit">{f.units.humidity}</span></th>
                <th scope="col">{f.temperature}<span class="unit">{f.units.temperature}</span></th>
              </tr>
            </thead>
            <tbody>
              {#each hours as hour (hour.time)}
                <tr>
                  <th scope="row">{formatTime(hour.time, locale)}</th>
                  <td>
                    {number(hour.cloud_cover, 0)}
                    <span class="layers" title={f.layers}>
                      {[hour.cloud_low, hour.cloud_mid, hour.cloud_high].map((v) => (v === null ? "—" : formatDecimal(v, locale, 0))).join(" · ")}
                    </span>
                  </td>
                  <td>
                    {number(hour.precipitation, 1)}
                    {#if hour.precipitation_probability !== null}<span class="layers">{percent(hour.precipitation_probability)}</span>{/if}
                  </td>
                  <td>
                    {number(hour.wind_speed, 0)}
                    {#if hour.wind_gusts !== null}<span class="layers">{number(hour.wind_gusts, 0)}</span>{/if}
                  </td>
                  <td>{number(hour.humidity, 0)}</td>
                  <td>{number(hour.temperature, 0)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="caption">{f.notes}</p>
      {:else if forecastNote}
        <p class="muted">{forecastNote}</p>
      {/if}
      {#if fetchedAgo !== null}
        <p class="caption">{f.from(PROVIDERS[forecast.provider], formatDuration(fetchedAgo))}</p>
      {/if}
      {#if forecast.error && hours.length === 0}
        <p class="caption">{f.failed(forecast.error)}</p>
      {/if}
    </div>
  {/if}
</Section>

<style>
  .readouts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3);
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .readout {
    font-size: 20px;
    line-height: 26px;
  }
  p {
    margin: 0;
  }
  .caption {
    color: var(--muted);
  }
  .warning {
    color: var(--warning);
  }
  .forecast {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h3 {
    margin: 0;
    color: var(--muted);
  }
  /* The table scrolls inside the card on a narrow phone, never the page. */
  .scroll {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    line-height: 18px;
    font-variant-numeric: tabular-nums;
  }
  th,
  td {
    padding: var(--space-1) var(--space-2) var(--space-1) 0;
    text-align: left;
    vertical-align: top;
    white-space: nowrap;
  }
  thead th {
    color: var(--muted);
    font-weight: 500;
    font-size: 12px;
  }
  tbody tr + tr {
    border-top: 1px solid var(--line);
  }
  tbody th {
    font-weight: 500;
  }
  .unit {
    display: block;
    font-size: 11px;
  }
  .layers {
    display: block;
    color: var(--muted);
    font-size: 12px;
  }
</style>
