<script lang="ts">
  // Tonight's weather: conditions from the weather role (ADR 0017), temperature,
  // humidity and dew point, how far the air is from dew, and which device says so.
  // Closed, its header still says the temperature and the margin, and warns of dew.
  import { formatDecimal, formatTemperature } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import type { WeatherState } from "../lib/types";
  import Section from "./Section.svelte";

  let { weather, open, ontoggle }: { weather: WeatherState; open: boolean; ontoggle: (open: boolean) => void } =
    $props();

  // Below this margin optics start to dew up without heaters.
  const DEW_MARGIN = 3;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const margin = $derived(
    weather.temperature !== null && weather.dew_point !== null ? weather.temperature - weather.dew_point : null,
  );
  const summary = $derived(
    [
      weather.temperature === null ? null : formatTemperature(weather.temperature, locale),
      margin === null ? null : t.weather.margin(formatTemperature(margin, locale)),
    ]
      .filter((part) => part !== null)
      .join(" · "),
  );
  const status = $derived(
    margin !== null && margin < DEW_MARGIN ? { tone: "warning" as const, text: t.weather.dewNearShort } : null,
  );
</script>

<Section scope="tonight" id="weather" title={t.weather.title} {summary} {status} {open} {ontoggle}>
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
  .caption {
    margin: 0;
    color: var(--muted);
  }
  .warning {
    color: var(--warning);
  }
</style>
