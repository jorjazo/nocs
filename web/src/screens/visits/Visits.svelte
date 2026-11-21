<script lang="ts">
  // Visitors (#/visits): the night's image for people watching it, and the only view
  // of a device that is not paired when the owner lets others watch. The image (the
  // live stack or the last capture, each visitor's choice), what it is of, how it was
  // taken, the temperature and humidity, and a full-size JPEG of it to keep. Night
  // mode is there, off unless the visitor turns it on.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import ImageScreen from "../../components/ImageScreen.svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import { auth } from "../../lib/auth.svelte";
  import { catalogObjects, plannedName } from "../../lib/catalog.svelte";
  import { exploreLayout } from "../../lib/explore.svelte";
  import { formatDecimal, formatDuration, formatPlain, formatTemperature, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { AroundMount } from "../../lib/pointed.svelte";
  import { stackView, type StackView } from "../../lib/stackview.svelte";
  import { objectName, objectSummary } from "../../lib/targets";
  import { forecastHours, frameRadius, pointedAt, type Sky } from "../../lib/tonightcards";
  import type { CatalogObject } from "../../lib/types";
  import Viewer from "../explore/Viewer.svelte";

  const t = $derived(i18n.t);
  const v = $derived(t.visits);
  const locale = $derived(i18n.locale);

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 60_000);
    return () => clearInterval(timer);
  });

  // -- The image ---------------------------------------------------------------------

  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const preview = $derived(camera?.preview ?? null);
  const stack = $derived(live.app.stack?.current ?? null);
  const stacked = $derived(stack?.preview ?? null);
  // The stack when the visitor asked for it and there is one; else the last capture.
  const showStack = $derived(stackView.view === "stack" && stacked !== null);
  const shown = $derived(showStack ? stacked : preview);
  const kind = $derived(showStack ? "stack" : "frame");

  // -- What it is of -------------------------------------------------------------------

  const mount = $derived(live.app.mount ?? null);
  const radius = $derived(frameRadius(camera?.field));
  const at = $derived<Sky | null>(mount ? { ra: mount.ra_j2000, dec: mount.dec_j2000 } : null);
  const watch = new AroundMount();
  $effect(() => watch.look(at, radius, now, !!mount?.slewing));
  const pointed = $derived(at ? pointedAt(at, radius, live.app.plan?.targets ?? [], watch.around) : null);
  const object = $derived.by((): { name: string; about: CatalogObject | null } | null => {
    switch (pointed?.kind) {
      case "planned": {
        const about = pointed.target.object ? catalogObjects.get(pointed.target.object) : null;
        return { name: plannedName(pointed.target, locale), about };
      }
      case "body":
        return { name: pointed.body === "sun" ? t.tonight.pointing.sun : t.tonight.pointing.moon, about: null };
      case "catalog":
        return { name: objectName(pointed.object, locale), about: pointed.object };
      default:
        return null;
    }
  });
  const size = $derived.by(() => {
    const about = object?.about;
    if (!about?.major_axis) return null;
    const major = formatDecimal(about.major_axis, locale, about.major_axis < 10 ? 1 : 0);
    return about.minor_axis ? `${major}′ × ${formatDecimal(about.minor_axis, locale, about.minor_axis < 10 ? 1 : 0)}′` : `${major}′`;
  });

  // -- How it was taken --------------------------------------------------------------

  const taken = $derived.by((): { label: string; value: string }[] => {
    if (showStack && stack) {
      return [
        { label: v.frames, value: formatPlain(stack.frames, locale) },
        { label: v.totalTime, value: formatDuration(stack.exposure) },
        { label: v.exposure, value: `${formatPlain(stack.setup.exposure, locale)} s` },
        ...(stack.setup.gain !== null ? [{ label: v.gain, value: formatPlain(stack.setup.gain, locale) }] : []),
        ...(stack.filter ? [{ label: v.filter, value: stack.filter }] : []),
      ];
    }
    const last = camera?.last_frame ?? null;
    if (!camera || !preview) return [];
    const filter = live.app.filter_wheel?.filter ?? null;
    return [
      ...(last ? [{ label: v.exposure, value: `${formatPlain(last.exposure, locale)} s` }] : []),
      ...(camera.gain !== null ? [{ label: v.gain, value: formatPlain(camera.gain, locale) }] : []),
      ...(filter ? [{ label: v.filter, value: filter }] : []),
      ...(last ? [{ label: v.at, value: formatTime(last.time, locale) }] : []),
    ];
  });

  // -- The night's air -------------------------------------------------------------

  const weather = $derived(live.app.weather ?? null);
  const forecast = $derived(live.app.forecast ?? null);
  // The sensor's reading, else the forecast's hour now.
  const air = $derived.by((): { temperature: number | null; humidity: number | null; forecast: boolean } | null => {
    if (weather && (weather.temperature !== null || weather.humidity !== null)) {
      return { temperature: weather.temperature, humidity: weather.humidity, forecast: false };
    }
    const hour = forecast ? forecastHours(forecast.hours, now, now + 3600_000)[0] : undefined;
    return hour ? { temperature: hour.temperature, humidity: hour.humidity, forecast: true } : null;
  });

  // -- Layout ----------------------------------------------------------------------

  const portrait = $derived(exploreLayout.orientation === "portrait");
  const sheetOpen = $derived(portrait && exploreLayout.open("panel"));
  let expanded = $state(false);
  const observer = $derived(auth.status?.role === "observer");
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && expanded && !document.querySelector("dialog[open]")) expanded = false;
  }} />

<h1 class="visually-hidden">{v.title}</h1>

<ImageScreen
  {portrait}
  {expanded}
  alone={observer}
  {sheetOpen}
  stageLabel={v.image}
  panelLabel={v.about}
  openLabel={v.open}
  closeLabel={v.close}
  ontogglesheet={() => exploreLayout.toggle("panel")}>
  {#snippet image()}
    <Viewer
      url={shown?.url ?? null}
      width={shown?.width ?? 0}
      height={shown?.height ?? 0}
      label={showStack ? v.stackLabel : v.frameLabel}
      reticle={false}
      ontap={() => (expanded = !expanded)}>
      {#snippet empty()}
        <div class="waiting">
          <Icon name="camera" size={32} />
          <p class="heading">{v.waiting}</p>
          <p class="muted">{v.waitingBody}</p>
        </div>
      {/snippet}
    </Viewer>
  {/snippet}
  {#snippet body()}
    <div class="top">
      <h2>{object?.name ?? v.title}</h2>
      <ThemeButton />
    </div>
    {#if object?.about}
      <p class="muted">
        {objectSummary(object.about, t, locale)}{size ? ` · ${size}` : ""}
      </p>
    {/if}
    {#if stacked && preview}
      <SegmentedControl
        label={v.show}
        options={[
          { value: "stack" as StackView, label: v.showStack },
          { value: "frame" as StackView, label: v.showFrame },
        ]}
        value={showStack ? "stack" : "frame"}
        onchange={(view) => stackView.set(view)} />
    {/if}
    {#if taken.length}
      <section aria-label={showStack ? v.stackTaken : v.frameTaken}>
        <h3 class="label muted">{showStack ? v.stackTaken : v.frameTaken}</h3>
        <dl class="facts">
          {#each taken as fact (fact.label)}
            <div>
              <dt class="muted">{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          {/each}
        </dl>
      </section>
    {/if}
    {#if air}
      <section aria-label={v.air}>
        <h3 class="label muted">{air.forecast ? v.airForecast : v.air}</h3>
        <dl class="facts">
          <div>
            <dt class="muted">{v.temperature}</dt>
            <dd>{air.temperature === null ? "—" : formatTemperature(air.temperature, locale, 0)}</dd>
          </div>
          <div>
            <dt class="muted">{v.humidity}</dt>
            <dd>{air.humidity === null ? "—" : `${formatDecimal(air.humidity, locale, 0)} %`}</dd>
          </div>
        </dl>
      </section>
    {/if}
    {#if observer}
      <Banner icon="eye">
        {t.link.observer}
        {#snippet action()}
          <Button variant="text" onclick={() => (auth.wantsPair = true)}>{t.link.pair}</Button>
        {/snippet}
      </Banner>
    {/if}
  {/snippet}
  {#snippet dock()}
    {#if shown}
      <a class="download" href="/api/visit/{kind}.jpg" download>
        <Icon name="download" size={20} />
        {showStack ? v.downloadStack : v.downloadFrame}
      </a>
      <p class="caption muted">{v.downloadHint}</p>
    {/if}
  {/snippet}
</ImageScreen>

<style>
  .waiting {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    text-align: center;
  }
  .waiting p {
    margin: 0;
  }
  .top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: 20px;
    line-height: 26px;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  p {
    margin: 0;
  }
  .label {
    margin: 0 0 var(--space-1);
    font-size: 13px;
    line-height: 18px;
    font-weight: 400;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: var(--space-2) var(--space-3);
    margin: 0;
  }
  .facts div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  dt {
    font-size: 12px;
    line-height: 16px;
  }
  dd {
    margin: 0;
    font-size: 17px;
    line-height: 24px;
  }
  .download {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--touch);
    background: var(--accent);
    color: var(--on-accent);
    min-height: var(--primary-height);
    font-size: 17px;
    font-weight: 600;
    text-decoration: none;
  }
  .caption {
    font-size: 12px;
    line-height: 16px;
    text-align: center;
  }
</style>
