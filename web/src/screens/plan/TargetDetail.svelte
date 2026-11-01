<script lang="ts">
  // A target's page (stage 3.6, #/plan/<id>): what it is, its altitude tonight
  // over the site's horizon, the framing chart with the main camera's frame,
  // and the actions: make it tonight's target, Go, and Go and centre. Moving
  // the chart frames off the object; Go goes where the frame points, and going
  // makes it tonight's target.
  import AltitudeChart from "../../components/AltitudeChart.svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import SkyChart from "../../components/SkyChart.svelte";
  import { ApiError, centerOn, choosePlanTarget, getTarget, getVisibility, gotoMount } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa, mountActivity } from "../../lib/mount.svelte";
  import { href } from "../../lib/router.svelte";
  import { separation, type Sky } from "../../lib/sky/projection";
  import { commonNames, objectSummary } from "../../lib/targets";
  import { tonight } from "../../lib/tonight.svelte";
  import type { CatalogObject, PlannedTarget, TargetVisibility } from "../../lib/types";
  import CenteringCard from "../live/CenteringCard.svelte";

  let { id }: { id: string } = $props();

  const MIN_ALTITUDE = 30;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);
  const planned = $derived(live.app.plan?.target ?? null);
  const almanac = $derived(tonight.almanac);
  const mount = $derived(live.app.mount ?? null);

  let object: CatalogObject | null = $state(null);
  let missing = $state(false);
  let failed = $state("");
  let seen: TargetVisibility | null = $state(null);

  $effect(() => {
    void tonight.load(live.app.equipment?.active ?? null);
  });

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 60_000);
    return () => clearInterval(timer);
  });

  $effect(() => {
    const designation = id;
    object = null;
    missing = false;
    failed = "";
    seen = null;
    getTarget(designation)
      .then((found) => {
        if (designation !== id) return;
        object = found;
        center = initialCenter(found);
        rotation = initialRotation(found);
      })
      .catch((e) => {
        if (designation !== id) return;
        if (e instanceof ApiError && e.status === 404) missing = true;
        else failed = errorText(e, t);
      });
    getVisibility([designation], MIN_ALTITUDE)
      .then((v) => {
        if (designation === id) seen = v.targets[0] ?? null;
      })
      .catch(() => {});
  });

  // -- Framing ------------------------------------------------------------------------

  // Tonight's target keeps its framing; anything else opens on the object.
  const isPlanned = (o: CatalogObject) => planned?.id === o.id;
  function initialCenter(o: CatalogObject): Sky {
    return planned && isPlanned(o) ? { ra: planned.ra, dec: planned.dec } : { ra: o.ra, dec: o.dec };
  }
  function initialRotation(o: CatalogObject): number {
    const wanted = planned && isPlanned(o) ? (planned.rotation ?? null) : null;
    if (wanted !== null) return Math.round(wanted);
    // The camera as it is: the angle of the last solved frame.
    const last = live.app.solver?.last?.rotation;
    return last === undefined || last === null ? 0 : Math.round(last) % 360;
  }

  let center: Sky = $state({ ra: 0, dec: 0 });
  let rotation = $state(0);
  const field = $derived(live.app.cameras?.main_camera?.field ?? null);
  const span = $derived(field ? Math.max(1, Math.max(field.width, field.height) * 2.2) : 4);
  // How far the frame was moved off the object, arcminutes.
  const offset = $derived(object ? separation(center, object) * 60 : 0);
  const moved = $derived(offset > 0.5);

  const chosen = $derived.by(() => {
    const o = object;
    const p = planned;
    if (!o || !p || p.id !== o.id || separation(center, p) * 60 >= 0.5) return false;
    const wanted = p.rotation ?? null;
    return wanted === null ? rotation === 0 : Math.round(wanted) === rotation;
  });

  function plannedTarget(o: CatalogObject): PlannedTarget {
    const name = commonNames(o, locale)[0];
    return {
      id: o.id,
      name: name ? `${o.label} · ${name}` : o.label,
      ra: center.ra,
      dec: center.dec,
      rotation,
    };
  }

  // -- Actions ------------------------------------------------------------------------

  let busy = $state<string | null>(null);
  let error = $state("");
  let refused = $state<"goto" | "center" | null>(null);

  const mountJob = $derived(holder(live.app.jobs, "mount"));
  const goReason = $derived.by((): string | null => {
    if (!owner) return t.plan.ownerOnly;
    if (!mount) return t.plan.noMount;
    if (mount.parked) return t.plan.parked;
    if (mountJob) return t.plan.mountBusy;
    return null;
  });
  const centerReason = $derived.by((): string | null => {
    if (goReason) return goReason;
    if (!live.app.solver?.available) return t.center.noSolver;
    if (!live.app.cameras?.main_camera) return t.center.noCamera;
    if (holder(live.app.jobs, "main_camera")) return t.center.cameraBusy;
    return null;
  });

  async function choose(): Promise<void> {
    if (!object) return;
    busy = "choose";
    error = "";
    try {
      await choosePlanTarget(plannedTarget(object));
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  async function go(kind: "goto" | "center", force = false): Promise<void> {
    if (!object) return;
    const target = plannedTarget(object);
    busy = kind;
    error = "";
    refused = null;
    try {
      if (kind === "center") await centerOn({ ra: target.ra, dec: target.dec, force });
      else await gotoMount({ frame: "j2000", ra: target.ra, dec: target.dec, force });
      // Going there makes it tonight's target, for Tonight's checklist and later the sequence.
      await choosePlanTarget(target);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message.includes("below the horizon")) refused = kind;
      else error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  // The latest centring, while it is about this frame.
  const centering = $derived.by(() => {
    const c = live.app.centering ?? null;
    if (!c || !object) return null;
    return separation(c.target, center) * 60 < 1 || separation(c.target, object) * 60 < 1 ? c : null;
  });
  const activity = $derived(mount ? mountActivity(mount, t) : null);
</script>

<div class="page">
  <a class="back" href={href({ screen: "plan" })}><Icon name="chevronLeft" />{t.tabs.plan}</a>

  {#if missing}
    <EmptyState icon="plan" title={t.plan.missing} body={t.plan.missingBody(id)} />
  {:else if failed}
    <Banner icon="alert" tone="error">{failed}</Banner>
  {:else if !object}
    <p class="muted" role="status">{t.plan.loading}</p>
  {:else}
    {@const names = commonNames(object, locale)}
    <header class="title">
      <span class="eyebrow muted">{object.label}{object.label !== object.id ? ` · ${object.id}` : ""}</span>
      <h1>{names[0] ?? object.label}</h1>
      <p class="summary muted">{objectSummary(object, t, locale)}</p>
      <p class="coordinates muted mono">{formatRa(object.ra)} · {formatDec(object.dec)}</p>
    </header>

    <section class="card" aria-labelledby="tonight-title">
      <div class="row">
        <h2 id="tonight-title">{t.plan.tonight}</h2>
        {#if seen}
          <Chip tone={seen.observable > 0 ? "ok" : "neutral"}>
            {seen.observable > 0 ? t.plan.upFor(formatDuration(seen.observable)) : seen.above_horizon > 0 ? t.plan.lowTonight : t.plan.notUp}
          </Chip>
        {/if}
      </div>
      {#if seen && almanac && almanac.times.length === seen.altitude.length}
        <AltitudeChart
          times={almanac.times}
          sunAltitude={almanac.sun_altitude}
          altitude={seen.altitude}
          horizon={seen.horizon}
          moon={almanac.moon.altitude}
          minAltitude={MIN_ALTITUDE}
          {now} />
        <p class="legend muted">{t.plan.legend(MIN_ALTITUDE)}</p>
        <div class="facts">
          <div>
            <span class="label muted">{t.plan.transit}</span>
            <span class="readout">{seen.transit ? formatTime(seen.transit, locale) : "—"}</span>
            <span class="muted">{t.plan.at(formatDecimal(seen.transit_altitude, locale, 0))}</span>
          </div>
          <div>
            <span class="label muted">{t.plan.best}</span>
            <span class="readout">{seen.best ? `${formatTime(seen.best.start, locale)}–${formatTime(seen.best.end, locale)}` : "—"}</span>
            <span class="muted">{t.plan.aboveMinimum(MIN_ALTITUDE)}</span>
          </div>
          <div>
            <span class="label muted">{t.plan.moon}</span>
            <span class="readout">{formatDecimal(seen.moon_separation, locale, 0)}°</span>
            <span class="muted">{t.tonight.lit(formatDecimal(almanac.moon.fraction * 100, locale, 0))}</span>
          </div>
        </div>
      {:else if tonight.missingSite}
        <p class="muted">{t.tonight.noSite}</p>
      {:else}
        <p class="muted" role="status">{t.tonight.loading}</p>
      {/if}
    </section>

    <section class="card framing" aria-labelledby="framing-title">
      <div class="row">
        <h2 id="framing-title">{t.plan.framing}</h2>
        {#if chosen}<Chip tone="accent">{t.plan.isTonights}</Chip>{/if}
      </div>
      {#if !field}<p class="muted">{t.plan.noField}</p>{/if}
      <div class="chart">
        {#key object.id}
          <SkyChart target={{ ra: object.ra, dec: object.dec }} bind:center {span} {field} {rotation} highlight={object.id} />
        {/key}
      </div>
      <p class="caption muted">
        {#if moved}
          {t.plan.moved(formatDecimal(offset, locale, offset < 10 ? 1 : 0))}
          <button type="button" class="link" onclick={() => object && (center = { ra: object.ra, dec: object.dec })}>{t.plan.recenter}</button>
        {:else}
          {t.plan.chartHint}
        {/if}
      </p>
      <label class="rotation">
        <span class="label muted">{t.plan.rotation} <span class="mono">{rotation}°</span></span>
        <input type="range" min="0" max="359" step="1" bind:value={rotation} />
        <span class="caption muted">{t.plan.rotationHint}</span>
      </label>
    </section>

    <section class="card actions" aria-label={t.plan.actions}>
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      {#if refused}
        <Banner icon="alert" tone="warning">
          {t.mount.belowHorizon}
          {#snippet action()}
            <ConfirmButton label={t.mount.goAnyway} confirmLabel={t.mount.goAnywayConfirm} onconfirm={() => refused && void go(refused, true)} />
          {/snippet}
        </Banner>
      {/if}
      <div class="buttons">
        <Button variant="primary" disabled={centerReason !== null} busy={busy === "center"} onclick={() => void go("center")}>
          {t.center.goCenter}
        </Button>
        <Button disabled={goReason !== null} busy={busy === "goto"} onclick={() => void go("goto")}>{t.mount.go}</Button>
        <Button variant="text" disabled={!owner || chosen} busy={busy === "choose"} onclick={() => void choose()}>
          {planned?.id === object.id ? t.plan.update : t.plan.choose}
        </Button>
      </div>
      <p class="caption muted">{centerReason ?? goReason ?? (moved ? t.plan.goesToFrame : t.plan.goHint)}</p>
      {#if activity?.moving}<p class="caption" role="status">{activity.text}</p>{/if}
      {#if centering}<CenteringCard {centering} />{/if}
    </section>
  {/if}
</div>

<style>
  .page {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding-top: var(--space-2);
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    color: var(--accent);
    text-decoration: none;
    align-self: flex-start;
  }
  .title {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h1 {
    margin: 0;
    font-size: 28px;
    line-height: 34px;
  }
  h2,
  p {
    margin: 0;
  }
  .summary {
    font-size: 15px;
    line-height: 20px;
  }
  .coordinates {
    font-size: 13px;
    line-height: 18px;
  }
  .eyebrow,
  .label,
  .caption,
  .legend {
    font-size: 12px;
    line-height: 16px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3);
  }
  .facts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .readout {
    font-size: 18px;
    line-height: 24px;
  }
  .chart {
    height: min(60dvh, 520px);
    min-height: 320px;
    margin: 0 calc(-1 * var(--space-4));
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
  .rotation {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .rotation input {
    min-height: var(--touch);
    accent-color: var(--accent);
  }
  .link {
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  @media (min-width: 420px) {
    .chart {
      margin: 0 calc(-1 * var(--space-6));
    }
  }
</style>
