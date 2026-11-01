<script lang="ts">
  // Tonight (stage 3.6), the home screen: conditions, the night from sunset to
  // sunrise with the dark window and the Moon, tonight's target, and the
  // get-ready checklist whose next pending step carries the one primary button
  // (docs/ux.md §1). Polar alignment and the sequence join it in their phases.
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import NightBar from "../../components/NightBar.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import WeatherCard from "../../components/WeatherCard.svelte";
  import { getVisibility } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration, formatTime } from "../../lib/format";
  import { guidingActive } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href, router, type Route } from "../../lib/router.svelte";
  import { nearest, phase } from "../../lib/sky/night";
  import { separation } from "../../lib/sky/projection";
  import { tonight } from "../../lib/tonight.svelte";
  import type { TargetVisibility } from "../../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const equipment = $derived(live.app.equipment ?? null);
  const profile = $derived(equipment?.active ?? null);
  const weather = $derived(live.app.weather ?? null);
  const almanac = $derived(tonight.almanac);
  const planned = $derived(live.app.plan?.target ?? null);

  $effect(() => {
    void tonight.load(profile);
  });

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => {
      now = Date.now();
      void tonight.load(profile);
    }, 60_000);
    return () => clearInterval(timer);
  });

  // -- The night -------------------------------------------------------------------

  const nightTitle = $derived.by(() => {
    if (!almanac) return t.tonight.title;
    const day = new Date(`${almanac.night}T12:00:00Z`);
    const text = new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }).format(day);
    return t.tonight.nightOf(text);
  });
  const darkFor = $derived(
    almanac?.dark ? (Date.parse(almanac.dark.end) - Date.parse(almanac.dark.start)) / 1000 : null,
  );
  const moonPhase = $derived(almanac ? phase(almanac.moon.phase) : null);

  // -- Tonight's target --------------------------------------------------------------

  let seen: TargetVisibility | null = $state(null);
  let seenFor = "";
  $effect(() => {
    const key = planned && almanac ? `${planned.ra},${planned.dec}|${almanac.night}` : "";
    if (key === seenFor) return;
    seenFor = key;
    seen = null;
    if (!planned || !almanac) return;
    getVisibility([`${planned.ra},${planned.dec}`])
      .then((v) => {
        if (seenFor === key) seen = v.targets[0] ?? null;
      })
      .catch(() => {});
  });
  const altitudeNow = $derived.by(() => {
    if (!seen || !almanac) return null;
    const i = nearest(almanac.times, now);
    return i === null ? null : (seen.altitude[i] ?? null);
  });

  // -- Checklist ----------------------------------------------------------------------

  interface Step {
    key: string;
    title: string;
    detail: string;
    done: boolean;
    action: string;
    route: Route;
  }

  const nightStart = $derived(almanac ? Date.parse(almanac.start) : now - 12 * 3600_000);
  const steps = $derived.by((): Step[] => {
    const connected = equipment?.connection === "connected";
    const list: Step[] = [
      {
        key: "connect",
        title: t.tonight.steps.connect,
        detail: connected && profile ? t.tonight.connected(equipment?.profiles[profile]?.name ?? profile) : t.tonight.notConnected,
        done: connected,
        action: t.tonight.openRig,
        route: { screen: "rig" },
      },
    ];
    if (live.app.focuser) {
      const run = live.app.autofocus ?? null;
      const tonightRun = run?.finished && Date.parse(run.finished) > nightStart ? run : null;
      const focused = tonightRun?.state === "succeeded";
      list.push({
        key: "focus",
        title: t.tonight.steps.focus,
        detail: focused
          ? t.tonight.focused(formatTime(tonightRun.finished ?? "", locale), tonightRun.hfr === null ? "—" : formatDecimal(tonightRun.hfr, locale, 2))
          : tonightRun
            ? t.tonight.focusFailed
            : t.tonight.notFocused,
        done: focused,
        action: t.tonight.focus,
        route: { screen: "focus" },
      });
    }
    const centering = live.app.centering ?? null;
    const centred =
      !!planned &&
      centering?.state === "succeeded" &&
      !!centering.finished &&
      Date.parse(centering.finished) > nightStart &&
      separation(centering.target, planned) * 60 <= Math.max(5, 2 * centering.tolerance);
    list.push({
      key: "frame",
      title: t.tonight.steps.frame,
      detail: !planned ? t.tonight.noTarget : centred ? t.tonight.centred(planned.name) : t.tonight.notCentred(planned.name),
      done: centred,
      action: planned ? t.tonight.openTarget : t.tonight.chooseTarget,
      route: planned?.id ? { screen: "target", id: planned.id } : { screen: "plan" },
    });
    if (live.app.cameras?.guide_camera || live.app.guiding?.equipment) {
      const guiding = guidingActive(live.app.guiding);
      list.push({
        key: "guide",
        title: t.tonight.steps.guide,
        detail: guiding ? t.tonight.guiding : t.tonight.notGuiding,
        done: guiding,
        action: t.tonight.openGuiding,
        route: { screen: "guiding" },
      });
    }
    return list;
  });
  const next = $derived(steps.find((s) => !s.done)?.key ?? null);
</script>

<ScreenHeader title={t.tabs.tonight}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

<div class="screen">
  {#if weather}<WeatherCard {weather} />{/if}

  <section class="card night" aria-labelledby="night-title">
    <h2 id="night-title">{nightTitle}</h2>
    {#if almanac}
      <NightBar {almanac} {now} />
      <div class="facts">
        <div>
          <span class="label muted">{t.tonight.dark}</span>
          {#if almanac.dark && darkFor !== null}
            <span class="readout">{formatTime(almanac.dark.start, locale)}–{formatTime(almanac.dark.end, locale)}</span>
            <span class="muted">
              {almanac.darkness === "astronomical" ? formatDuration(darkFor) : t.tonight.darkest(t.tonight.darkness[almanac.darkness ?? "civil"])}
            </span>
          {:else}
            <span class="readout">—</span>
            <span class="muted">{t.tonight.noDark}</span>
          {/if}
        </div>
        <div>
          <span class="label muted">{t.tonight.moon}</span>
          <span class="readout">{moonPhase ? t.tonight.phases[moonPhase] : "—"}</span>
          <span class="muted">
            {t.tonight.lit(formatDecimal(almanac.moon.fraction * 100, locale, 0))}
            {#if almanac.moon.rise}· {t.tonight.rises(formatTime(almanac.moon.rise, locale))}{/if}
            {#if almanac.moon.set}· {t.tonight.sets(formatTime(almanac.moon.set, locale))}{/if}
          </span>
        </div>
      </div>
      {#if almanac.dark_moonless.length && almanac.moon.fraction > 0.1}
        <p class="caption muted">
          {t.tonight.moonless(
            almanac.dark_moonless.map((i) => `${formatTime(i.start, locale)}–${formatTime(i.end, locale)}`).join(", "),
          )}
        </p>
      {/if}
    {:else if tonight.missingSite}
      <p class="muted">{t.tonight.noSite}</p>
      {#if auth.owner}
        <div><Button onclick={() => router.go({ screen: "rig" })}>{t.tonight.openRig}</Button></div>
      {/if}
    {:else if tonight.error}
      <p class="muted">{errorText(tonight.error, t)}</p>
      <div><Button onclick={() => tonight.load(profile, true)}>{t.tonight.retry}</Button></div>
    {:else}
      <p class="muted" role="status">{t.tonight.loading}</p>
    {/if}
  </section>

  {#if planned}
    <section class="card target" aria-labelledby="target-title">
      <div class="row">
        <h2 id="target-title">
          {#if planned.id}<a href={href({ screen: "target", id: planned.id })}>{planned.name}</a>{:else}{planned.name}{/if}
        </h2>
        {#if altitudeNow !== null}
          <Chip tone={altitudeNow > 0 ? "accent" : "neutral"}>{t.tonight.altitudeNow(formatDecimal(altitudeNow, locale, 0))}</Chip>
        {/if}
      </div>
      <p class="muted">
        {#if seen}
          {#if seen.observable > 0}
            {t.tonight.observable(formatDuration(seen.observable))}
            {#if seen.transit}· {t.tonight.transit(formatTime(seen.transit, locale), formatDecimal(seen.transit_altitude, locale, 0))}{/if}
          {:else}
            {t.tonight.notObservable}
          {/if}
        {:else}
          {t.tonight.target}
        {/if}
      </p>
    </section>
  {/if}

  <section class="card" aria-labelledby="checklist-title">
    <h2 id="checklist-title">{t.tonight.checklist}</h2>
    <ol class="steps">
      {#each steps as step (step.key)}
        <li class:done={step.done}>
          <span class="mark" aria-hidden="true">{step.done ? "✓" : ""}</span>
          <div class="text">
            <span class="title">{step.title}</span>
            <span class="muted">{step.detail}</span>
          </div>
          {#if !step.done || step.key === "frame"}
            <Button variant={step.key === next ? "primary" : "text"} onclick={() => router.go(step.route)}>{step.action}</Button>
          {/if}
          <span class="visually-hidden">{step.done ? t.tonight.stepDone : t.tonight.stepPending}</span>
        </li>
      {/each}
    </ol>
  </section>
</div>

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-4);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
  }
  p {
    margin: 0;
  }
  .facts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
  }
  .facts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .label,
  .caption {
    font-size: 12px;
    line-height: 16px;
  }
  .readout {
    font-size: 20px;
    line-height: 26px;
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .steps {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .steps li {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 56px;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--line);
  }
  .steps li:first-child {
    border-top: none;
  }
  .mark {
    flex: none;
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: var(--radius-full);
    border: 2px solid var(--muted);
    font-size: 13px;
    line-height: 1;
  }
  .done .mark {
    border-color: var(--ok);
    background: var(--ok);
    color: var(--bg);
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .title {
    font-weight: 500;
  }
</style>
