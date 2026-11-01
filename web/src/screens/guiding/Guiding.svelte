<script lang="ts">
  // Guiding as a full-screen flow (docs/ux.md §1, ADR 0022–0024): PHD2's state,
  // the graph with its RMS, and the actions that fit what PHD2 is doing now:
  // connect, loop, start guiding (calibrating first when needed), dither, stop.
  // Guiding belongs to the server: every client that opens this screen follows
  // the same run, and leaving it changes nothing.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import {
    cancelJob,
    connectGuiding,
    disconnectGuiding,
    ditherNow,
    loopGuiding,
    setGuidingExposure,
    startGuiding,
    stopGuiding,
  } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { capture } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain, formatSeconds } from "../../lib/format";
  import { guideGraph, guidingActive, LOOPING_STATES } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { JobInfo } from "../../lib/types";
  import GuideGraph from "./GuideGraph.svelte";

  let { offline = false }: { offline?: boolean } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const guiding = $derived(live.app.guiding ?? null);

  // What PHD2 is doing while a guide or dither job runs, in the app's language.
  const progressLine = $derived.by(() => {
    const step = guiding?.calibrating ?? null;
    if (step) {
      const n = formatPlain(step.step, locale);
      const moved = formatDecimal(step.distance, locale, 1);
      return t.guiding.calibrationStep[step.direction](n, moved);
    }
    if (guiding?.app_state === "Calibrating") return t.guiding.calibratingNow;
    if (guiding?.settling) return t.guiding.settlingNow;
    if (guiding?.app_state !== "Guiding") return t.guiding.findingStar;
    return "";
  });
  const reachable = $derived(guiding?.phd2.connected ?? false);
  const phd2State = $derived(guiding?.app_state ?? null);
  const active = $derived(guidingActive(guiding));
  const looping = $derived(phd2State !== null && LOOPING_STATES.has(phd2State));
  const connected = $derived(guiding?.equipment ?? false);
  const stats = $derived(guiding?.stats ?? null);
  const rig = $derived(!!live.app.cameras?.guide_camera && !!live.app.mount);

  // The graph: fetched once, then followed from the state.
  $effect(() => guideGraph.start());
  $effect(() => guideGraph.follow(stats));

  // A start of guiding or a dither in progress, from any client.
  const job = $derived.by((): { id: string; info: JobInfo } | null => {
    for (const [id, info] of Object.entries(live.app.jobs ?? {})) {
      if (info.state === "running" && (info.kind === "guide" || info.kind === "dither")) return { id, info };
    }
    return null;
  });
  // The last one that failed, until dismissed.
  let dismissed = $state<string | null>(null);
  const failed = $derived.by((): { id: string; info: JobInfo } | null => {
    let latest: { id: string; info: JobInfo } | null = null;
    for (const [id, info] of Object.entries(live.app.jobs ?? {})) {
      if (info.kind !== "guide" && info.kind !== "dither") continue;
      if (!latest || info.started > latest.info.started) latest = { id, info };
    }
    return latest && latest.info.state === "failed" && latest.id !== dismissed ? latest : null;
  });

  let units = $state<"arcsec" | "px">("arcsec");
  const scale = $derived(guiding?.pixel_scale ?? null);
  let recalibrate = $state(false);

  let busy = $state(false);
  let error = $state("");

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  function close(): void {
    router.back({ screen: "live" });
  }

  const blocked = $derived.by(() => {
    if (!auth.owner) return t.guiding.observer;
    if (!reachable) return t.guiding.unreachable;
    if (!rig) return t.guiding.noRig;
    return "";
  });

  const statusChip = $derived.by((): { tone: Tone; text: string } => {
    if (!reachable) return { tone: "error", text: t.guiding.unreachable };
    const text = phd2State ? t.guiding.state[phd2State] : t.guiding.unknown;
    if (phd2State === "Guiding") {
      return guiding?.settling ? { tone: "accent", text: `${text} · ${t.guiding.settling}` } : { tone: "ok", text };
    }
    if (phd2State === "LostLock") return { tone: "error", text };
    if (phd2State === "Calibrating" || looping) return { tone: "accent", text };
    return { tone: "neutral", text };
  });
  const settingsTone = $derived(
    guiding?.settings === "failed" ? "error" : guiding?.settings === "applied" || guiding?.settings === "user" ? "ok" : "warning",
  );

  // RMS in the units shown, with pixels underneath when showing arcseconds.
  function rms(arcsec: number | null | undefined, px: number | null | undefined): string {
    const value = units === "arcsec" && arcsec != null ? arcsec : px;
    if (value === null || value === undefined) return "—";
    return `${formatDecimal(value, locale, 2)}${units === "arcsec" && arcsec != null ? "″" : " px"}`;
  }

  // Exposures PHD2 commonly uses.
  const EXPOSURES = [0.5, 1, 1.5, 2, 3, 4, 5];
  const exposure = $derived(guiding?.exposure ?? null);
  function pickExposure(value: string): void {
    void act(() => setGuidingExposure(Number(value)));
  }

  let ditherPixels = $state<number | null>(capture.ditherPixels);
  $effect(() => {
    if (ditherPixels !== null) capture.setDitherPixels(ditherPixels);
  });

  const calibration = $derived(guiding?.calibration ?? null);
  // The star's figures come from the last guide step (a dither or a lost frame has none).
  const lastStep = $derived([...guideGraph.entries].reverse().find((e) => e.kind === "step") ?? null);
  const alert = $derived(guiding?.alert ?? null);
  let alertSeen = $state<string | null>(null);
</script>

<main class="flow">
  <header class="header">
    <button type="button" class="close" aria-label={t.guiding.close} onclick={close}>
      <Icon name="close" />
    </button>
    <div class="titles">
      <p class="caption muted">{t.guiding.phd2}{guiding?.phd2.version ? ` ${guiding.phd2.version}` : ""}</p>
      <h1 class="title">{t.guiding.title}</h1>
    </div>
    <ThemeButton />
  </header>

  {#if offline}<Banner icon="offline" tone="warning">{t.link.offline}</Banner>{/if}

  <section class="status">
    <Chip tone={statusChip.tone}>{statusChip.text}</Chip>
    {#if reachable && guiding}
      <p class="caption"><Chip tone={settingsTone}>{t.guiding.settings[guiding.settings]}</Chip></p>
      <p class="caption muted">
        {t.guiding.equipment}: {connected ? t.guiding.equipmentOn : t.guiding.equipmentOff}
        {#if exposure !== null}· {formatSeconds(exposure, locale)}{/if}
      </p>
    {:else}
      <p class="caption muted">{t.guiding.unreachableHint}</p>
    {/if}
  </section>

  {#if guiding?.error}<Banner icon="alert" tone="error">{guiding.error}</Banner>{/if}
  {#if alert && alert.time !== alertSeen}
    <Banner icon="alert" tone={alert.kind === "error" ? "error" : "warning"}>
      {alert.message}
      {#snippet action()}
        <Button variant="text" onclick={() => (alertSeen = alert.time)}>{t.live.dismiss}</Button>
      {/snippet}
    </Banner>
  {/if}

  <GuideGraph entries={guideGraph.entries} {scale} {units} />
  <div class="graphbar">
    <p class="caption muted">
      {stats && stats.steps > 0 ? t.guiding.steps(stats.steps) : t.guiding.noSteps}
      {#if stats && stats.lost > 0}· {t.guiding.lost(stats.lost)}{/if}
    </p>
    {#if scale}
      <SegmentedControl
        label={t.guiding.units}
        options={[
          { value: "arcsec", label: t.guiding.arcsec },
          { value: "px", label: t.guiding.pixels },
        ]}
        value={units}
        onchange={(value) => (units = value === "px" ? "px" : "arcsec")} />
    {/if}
  </div>

  <section class="readouts" aria-label={t.guiding.rms}>
    <div>
      <span class="label muted">{t.guiding.rms} {t.guiding.ra}</span>
      <span class="readout mono ra">{rms(stats?.rms_ra, stats?.rms_ra_px)}</span>
    </div>
    <div>
      <span class="label muted">{t.guiding.rms} {t.guiding.dec}</span>
      <span class="readout mono dec">{rms(stats?.rms_dec, stats?.rms_dec_px)}</span>
    </div>
    <div>
      <span class="label muted">{t.guiding.rms} {t.guiding.total}</span>
      <span class="readout mono">{rms(stats?.rms_total, stats?.rms_total_px)}</span>
    </div>
    <div>
      <span class="label muted">{t.guiding.snr} · {t.guiding.hfd}</span>
      <span class="readout mono">
        {lastStep?.snr != null ? formatPlain(Math.round(lastStep.snr), locale) : "—"} ·
        {lastStep?.hfd != null ? formatDecimal(lastStep.hfd, locale, 1) : "—"}
      </span>
    </div>
  </section>

  {#if job}
    <section class="progress" aria-live="polite">
      <p class="body">{job.info.kind === "dither" ? t.guiding.dithering : t.guiding.starting}</p>
      {#if progressLine}<p class="caption muted mono">{progressLine}</p>{/if}
    </section>
  {/if}

  <div class="actions">
    {#if blocked}<p class="caption muted">{blocked}</p>{/if}
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
    {#if failed}
      <Banner icon="alert" tone="error">
        {failed.info.error}
        {#snippet action()}
          <Button variant="text" onclick={() => (dismissed = failed.id)}>{t.live.dismiss}</Button>
        {/snippet}
      </Banner>
    {/if}

    {#if active || job}
      {#if phd2State === "Guiding" && !job}
        <div class="row">
          <Stepper label={t.guiding.ditherAmount} bind:value={ditherPixels} min={1} max={100} unit="px" hint={t.guiding.ditherHint} />
          <Button
            {busy}
            disabled={!!blocked || ditherPixels === null}
            onclick={() => void act(() => ditherNow({ pixels: ditherPixels ?? capture.ditherPixels }))}>
            {t.guiding.dither}
          </Button>
        </div>
      {/if}
      <Button variant="danger" wide {busy} disabled={!auth.owner || !reachable} onclick={() => void act(async () => {
        if (job) await cancelJob(job.id);
        await stopGuiding();
      })}>
        {t.guiding.stop}
      </Button>
    {:else}
      {#if connected}
        <div class="group">
          <span class="label muted">{t.guiding.exposure}</span>
          <SegmentedControl
            label={t.guiding.exposure}
            options={EXPOSURES.map((value) => ({ value: String(value), label: formatSeconds(value, locale) }))}
            value={exposure !== null ? String(exposure) : ""}
            disabled={!!blocked || busy}
            onchange={pickExposure} />
        </div>
        <Toggle
          label={t.guiding.recalibrate}
          hint={t.guiding.recalibrateHint}
          checked={recalibrate}
          disabled={!!blocked}
          onchange={(value) => (recalibrate = value)} />
      {/if}
      <Button variant="primary" wide {busy} disabled={!!blocked} onclick={() => void act(() => startGuiding({ recalibrate }))}>
        {t.guiding.guide}
      </Button>
      <div class="row">
        {#if looping}
          <Button {busy} disabled={!!blocked} onclick={() => void act(stopGuiding)}>{t.guiding.stopLoop}</Button>
        {:else}
          <Button {busy} disabled={!!blocked} onclick={() => void act(() => loopGuiding())}>{t.guiding.loop}</Button>
        {/if}
        {#if connected}
          <Button {busy} disabled={!auth.owner || !reachable} onclick={() => void act(disconnectGuiding)}>{t.guiding.disconnect}</Button>
        {:else}
          <Button {busy} disabled={!!blocked} onclick={() => void act(connectGuiding)}>{t.guiding.connect}</Button>
        {/if}
      </div>
      {#if connected}<p class="caption muted">{t.guiding.cameraTaken}</p>{/if}
    {/if}
  </div>

  <section class="calibration">
    <h2 class="label muted">{t.guiding.calibration}</h2>
    {#if calibration}
      <p class="body">
        {calibration.declination !== null
          ? t.guiding.calibrated(`${formatDecimal(calibration.declination, locale, 1)}°`)
          : t.guiding.calibration}
      </p>
      <p class="caption muted mono">
        {t.guiding.rates(formatDecimal(calibration.ra_rate, locale, 2), formatDecimal(calibration.dec_rate, locale, 2))}
      </p>
    {:else}
      <p class="caption muted">{t.guiding.notCalibrated}</p>
    {/if}
  </section>
</main>

<style>
  .flow {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    max-width: 640px;
    margin: 0 auto;
    padding: env(safe-area-inset-top) var(--margin) calc(env(safe-area-inset-bottom) + var(--space-6));
  }
  .header {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-3);
    padding-top: var(--space-4);
  }
  .close {
    display: grid;
    place-items: center;
    width: var(--touch);
    height: var(--touch);
    border: 1px solid var(--line);
    border-radius: var(--radius-full);
    background: var(--raised);
    color: var(--text);
    cursor: pointer;
  }
  .titles {
    min-width: 0;
  }
  .status,
  .actions,
  .progress,
  .calibration,
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .status {
    align-items: flex-start;
  }
  .status p,
  .actions p,
  .progress p,
  .calibration p,
  .calibration h2 {
    margin: 0;
  }
  .graphbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    margin-top: calc(-1 * var(--space-2));
  }
  .graphbar p {
    margin: 0;
  }
  .readouts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--raised);
  }
  .readout {
    font-size: 20px;
    line-height: 26px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .readout.ra {
    color: var(--guide-ra);
  }
  .readout.dec {
    color: var(--guide-dec);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-2);
  }
  .row > :global(*) {
    flex: 1 1 140px;
  }
  @media (min-width: 768px) {
    .readouts {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
  }
</style>
