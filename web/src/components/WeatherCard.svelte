<script lang="ts">
  // Conditions from the weather role (ADR 0017): temperature, humidity and dew
  // point, and how far the air is from dew.
  import { formatDecimal, formatTemperature } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import type { WeatherState } from "../lib/types";

  let { weather }: { weather: WeatherState } = $props();

  // Below this margin optics start to dew up without heaters.
  const DEW_MARGIN = 3;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const margin = $derived(
    weather.temperature !== null && weather.dew_point !== null ? weather.temperature - weather.dew_point : null,
  );
</script>

<section class="card" aria-labelledby="weather-title">
  <h2 class="heading" id="weather-title">{t.weather.title}</h2>
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
</section>

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
  }
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
