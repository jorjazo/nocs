<script lang="ts">
  // Polar alignment as a full-screen flow (docs/ux.md §1–2, ADR 0034): settings
  // and where to start, the three points as they are solved, then the target
  // with what to do with each knob, updated with every frame, and the result.
  // The run belongs to the server: any client that opens this screen while one
  // runs follows it. Finishing goes back to the start; stopping stays put.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import Icon from "../../components/Icon.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { cancelJob, finishPolarAlign, gotoMount, startPolarAlign } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { advice, hourAngle, suggestedStart, type AxisError } from "../../lib/polar";
  import { router } from "../../lib/router.svelte";
  import { separation } from "../../lib/sky/projection";
  import type { PolarAlignmentState, PolarPoint } from "../../lib/types";
  import { formatAngle } from "./angle";
  import PolarTarget from "./PolarTarget.svelte";

  let { offline = false }: { offline?: boolean } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const run = $derived(live.app.polar_alignment ?? null);
  const mount = $derived(live.app.mount ?? null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const running = $derived(run?.state === "running");
  const site = $derived(mount?.site ?? null);

  // The run this screen shows: the one running, or the one it started or
  // watched until the user asks for another.
  let watched = $state<string | null>(null);
  $effect(() => {
    if (run && running) watched = run.job;
  });
  const shown = $derived(run && (running || watched === run.job) ? run : null);
  const step = $derived(!shown ? 1 : !running ? 4 : shown.axis === null ? 2 : 3);

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 5000);
    return () => clearInterval(timer);
  });

  function close(): void {
    router.back({ screen: "tonight" });
  }

  // -- Settings ---------------------------------------------------------------------

  // The last run's choices, if any (also another client's).
  const previous = untrack(() => live.app.polar_alignment?.options ?? null);
  let exposure = $state<number | null>(previous?.exposure ?? null);
  let exposureValid = $state(true);
  let binning = $state<number | null>(previous?.binning ?? null);
  let rotation = $state(previous?.step ?? 30);
  let side = $state<"auto" | "east" | "west">("auto");
  let tolerance = $state(previous?.tolerance ?? 1);
  let back = $state(previous?.back ?? true);
  let advanced = $state(false);

  const binnings = $derived(
    [1, 2, 3, 4].filter((b) => b <= (camera?.max_binning ?? 1)).map((b) => ({ value: String(b), label: `${b}×${b}` })),
  );

  // Meaningless at the pole, where the mounts park.
  const hourAngleNow = $derived(
    mount && site && Math.abs(mount.dec) < 89 ? hourAngle(mount.ra, new Date(now), site.longitude) : null,
  );
  const suggested = $derived(site ? suggestedStart(site.latitude, site.longitude, new Date(now)) : null);
  const nearStart = $derived(!!mount && !!suggested && separation(mount, suggested) < 3);

  const busyJob = $derived(holder(live.app.jobs, "mount") ?? holder(live.app.jobs, "main_camera"));
  const blocked = $derived.by(() => {
    if (!auth.owner) return t.polar.observer;
    if (!mount || !camera) return t.polar.noRig;
    if (!live.app.solver?.available) return t.polar.noSolver;
    if (!site) return t.polar.noSite;
    if (mount.parked) return t.polar.parked;
    if (busyJob) return t.polar.busy;
    return "";
  });

  let busy = $state<"start" | "goto" | "finish" | "stop" | null>(null);
  // The run asked to finish: it ends after the frame being taken.
  let finishing = $state<string | null>(null);
  let error = $state("");

  async function act(name: NonNullable<typeof busy>, action: () => Promise<unknown>): Promise<void> {
    busy = name;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  function goToStart(): void {
    if (!site) return;
    const start = suggestedStart(site.latitude, site.longitude, new Date());
    void act("goto", () => gotoMount({ frame: "jnow", ra: start.ra, dec: start.dec }));
  }

  function start(): void {
    void act("start", async () => {
      watched = await startPolarAlign({ exposure, binning, step: rotation, side, tolerance, back });
    });
  }

  // -- The run --------------------------------------------------------------------

  function pointName(run: PolarAlignmentState, index: number): string {
    if (index === 0) return t.polar.here;
    const degrees = formatDecimal(run.options.step * index, locale, 0);
    return t.polar.turnedBy(degrees, run.options.side === "east" ? t.polar.sideEast : t.polar.sideWest);
  }

  function pointStatus(run: PolarAlignmentState, point: PolarPoint | undefined): string {
    if (!point) return t.polar.waiting;
    if (point.solution && point.hour_angle !== null && point.dec !== null) {
      return t.polar.solved(hours(point.hour_angle), degrees(point.dec));
    }
    return run.phase && run.phase !== "adjusting" ? t.polar.phase[run.phase] : t.polar.waiting;
  }

  function hours(value: number): string {
    return `${formatDecimal(value, locale, 2)} h`;
  }

  function degrees(value: number): string {
    return `${formatDecimal(value, locale, 1)}°`;
  }

  const latest = $derived(shown?.updates.at(-1) ?? null);
  const trail = $derived(
    (shown?.updates ?? [])
      .slice(0, -1)
      .map((u) => u.axis)
      .filter((a): a is AxisError => a !== null),
  );
  const knobs = $derived(shown?.axis ? advice(shown.axis, shown.options.tolerance) : null);
  const eastRight = $derived((site?.latitude ?? 0) >= 0);
  const moved = $derived.by(() => {
    const k = latest?.knobs;
    if (!k) return null;
    const parts: string[] = [];
    if (Math.abs(k.altitude) >= 0.05) {
      parts.push((k.altitude > 0 ? t.polar.movedUp : t.polar.movedDown)(formatAngle(k.altitude, locale)));
    }
    if (Math.abs(k.azimuth) >= 0.05) {
      parts.push((k.azimuth > 0 ? t.polar.movedEast : t.polar.movedWest)(formatAngle(k.azimuth, locale)));
    }
    return parts.length ? t.polar.moved(parts.join(", ")) : t.polar.unchanged;
  });

  function again(): void {
    watched = null;
    error = "";
  }

  function above(axis: AxisError): string {
    return (axis.altitude >= 0 ? t.polar.above : t.polar.below)(formatAngle(axis.altitude, locale));
  }

  function eastOf(axis: AxisError): string {
    return (axis.azimuth >= 0 ? t.polar.eastOf : t.polar.westOf)(formatAngle(axis.azimuth, locale));
  }
</script>

<main class="flow">
  <header class="header">
    <button type="button" class="close" aria-label={t.polar.close} onclick={close}>
      <Icon name="close" />
    </button>
    <div class="titles">
      <p class="caption muted">{t.autofocus.stepOf(step, 4)} · {t.polar.steps[step - 1]}</p>
      <h1 class="title">{t.polar.title}</h1>
    </div>
    <ThemeButton />
  </header>
  <ol class="steps" aria-hidden="true">
    {#each t.polar.steps as name, i (name)}
      <li class:done={i + 1 < step} class:current={i + 1 === step}></li>
    {/each}
  </ol>

  {#if offline}<Banner icon="offline" tone="warning">{t.link.offline}</Banner>{/if}

  {#if !shown}
    <section class="readouts">
      <div>
        <span class="label muted">{t.polar.altitude}</span>
        <span class="readout mono">{mount?.alt != null ? degrees(mount.alt) : "—"}</span>
      </div>
      <div>
        <span class="label muted">{t.polar.hourAngle}</span>
        <span class="readout mono">{hourAngleNow !== null ? hours(hourAngleNow) : "—"}</span>
      </div>
      <div>
        <span class="label muted">{t.polar.dec}</span>
        <span class="readout mono">{mount ? degrees(mount.dec) : "—"}</span>
      </div>
      <div>
        <span class="label muted">{t.polar.latitude}</span>
        <span class="readout mono">{site ? degrees(site.latitude) : "—"}</span>
      </div>
    </section>

    {#if run && !running && run.axis}
      <p class="body muted last">
        {run.aligned
          ? t.polar.lastAligned(formatTime(run.finished ?? run.started, locale), formatAngle(run.axis.total, locale))
          : t.polar.last(formatTime(run.finished ?? run.started, locale), formatAngle(run.axis.total, locale))}
      </p>
    {/if}

    <section class="card start" aria-labelledby="polar-start">
      <h2 id="polar-start" class="label">{t.polar.where}</h2>
      <p class="body">
        {suggested ? t.polar.whereText(degrees(suggested.dec)) : t.polar.whereNoSite}
      </p>
      <p class="caption muted">{t.polar.whereHint}</p>
      {#if nearStart}
        <Chip tone="ok">{t.polar.atStart}</Chip>
      {:else if suggested && auth.owner}
        <div>
          <Button
            busy={busy === "goto"}
            disabled={!mount || mount.parked || !!busyJob || busy !== null}
            onclick={goToStart}>{t.polar.goStart}</Button>
        </div>
      {/if}
    </section>

    <section class="settings">
      <NumberField
        label={t.polar.exposure}
        bind:value={exposure}
        bind:valid={exposureValid}
        min={0.01}
        max={600}
        unit="s"
        hint={t.polar.exposureHint}
        placeholder={camera ? formatDecimal(camera.exposure, locale, 1) : ""} />
      {#if binnings.length > 1}
        <div class="group">
          <span class="label muted">{t.polar.binning}</span>
          <SegmentedControl
            label={t.polar.binning}
            options={[{ value: "", label: t.polar.cameraBinning }, ...binnings]}
            value={binning === null ? "" : String(binning)}
            onchange={(value) => (binning = value === "" ? null : Number(value))} />
        </div>
      {/if}
      <div class="group">
        <span class="label muted">{t.polar.rotation}</span>
        <SegmentedControl
          label={t.polar.rotation}
          options={[15, 30, 45].map((d) => ({ value: String(d), label: `${d}°` }))}
          value={String(rotation)}
          onchange={(value) => (rotation = Number(value))} />
        <span class="caption muted">{t.polar.rotationHint}</span>
      </div>

      <button type="button" class="disclosure" aria-expanded={advanced} onclick={() => (advanced = !advanced)}>
        <Icon name={advanced ? "chevronDown" : "chevronRight"} size={20} />
        {t.polar.advanced}
      </button>
      {#if advanced}
        <div class="group">
          <span class="label muted">{t.polar.side}</span>
          <SegmentedControl
            label={t.polar.side}
            options={[
              { value: "auto", label: t.polar.sideAuto },
              { value: "east", label: t.polar.sideEast },
              { value: "west", label: t.polar.sideWest },
            ]}
            value={side}
            onchange={(value) => (side = value === "east" || value === "west" ? value : "auto")} />
          <span class="caption muted">{t.polar.sideHint}</span>
        </div>
        <div class="group">
          <span class="label muted">{t.polar.tolerance}</span>
          <SegmentedControl
            label={t.polar.tolerance}
            options={[0.5, 1, 2, 5].map((a) => ({ value: String(a), label: formatAngle(a, locale) }))}
            value={String(tolerance)}
            onchange={(value) => (tolerance = Number(value))} />
        </div>
        <Toggle label={t.polar.back} hint={t.polar.backHint} checked={back} onchange={(value) => (back = value)} />
      {/if}
    </section>

    <div class="actions">
      {#if blocked}<p class="caption muted">{blocked}</p>{/if}
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <Button variant="primary" wide busy={busy === "start"} disabled={!!blocked || !exposureValid || busy !== null} onclick={start}>
        {t.polar.start}
      </Button>
    </div>
  {:else if running && shown.axis === null}
    <ol class="points">
      {#each [0, 1, 2] as index (index)}
        {@const point = shown.points[index]}
        {@const current = !!point && !point.solution}
        <li class:current class:solved={!!point?.solution}>
          <span class="marker" aria-hidden="true">
            {#if point?.solution}<Icon name="check" size={16} />{:else}{index + 1}{/if}
          </span>
          <div>
            <p class="body">{t.polar.point(index + 1)} · {pointName(shown, index)}</p>
            <p class="caption muted mono">{pointStatus(shown, point)}</p>
            {#if point?.failures.length}
              <p class="caption muted">{t.polar.retries(point.failures.length)}</p>
            {/if}
          </div>
        </li>
      {/each}
    </ol>
    <section class="progress" aria-live="polite">
      <div class="bar indeterminate" role="progressbar" aria-valuemin={0} aria-valuemax={3} aria-valuenow={shown.points.filter((p) => p.solution).length}>
        <span style:width="{(shown.points.filter((p) => p.solution).length / 3) * 100}%"></span>
      </div>
      <p class="body">{shown.phase ? t.polar.phase[shown.phase] : ""}</p>
    </section>
    <div class="actions">
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <Button variant="danger" wide busy={busy === "stop"} disabled={!auth.owner} onclick={() => void act("stop", () => cancelJob(shown.job))}>
        {t.polar.stop}
      </Button>
      <p class="caption muted">{t.polar.stopHint}</p>
    </div>
  {:else if running && shown.axis}
    <PolarTarget axis={shown.axis} {trail} tolerance={shown.options.tolerance} latitude={site?.latitude ?? -1} />

    <section class="error-line" aria-live="polite">
      <span class="total mono">{formatAngle(shown.axis.total, locale)}</span>
      <Chip tone={shown.aligned ? "ok" : "warning"}>{shown.aligned ? t.polar.aligned : t.polar.notAligned}</Chip>
    </section>

    {#if knobs && shown.phase === "adjusting"}
      <ul class="knobs">
        <li class:ok={knobs.altitude === "ok"}>
          <span class="knob-icon" aria-hidden="true">
            <Icon name={knobs.altitude === "ok" ? "check" : knobs.altitude === "raise" ? "up" : "down"} />
          </span>
          <div>
            <p class="instruction">
              {knobs.altitude === "ok"
                ? t.polar.altitudeOk
                : (knobs.altitude === "raise" ? t.polar.raise : t.polar.lower)(formatAngle(knobs.altitudeBy, locale))}
            </p>
            <p class="caption muted">{t.polar.altitudeKnob}</p>
          </div>
        </li>
        <li class:ok={knobs.azimuth === "ok"}>
          <span class="knob-icon" aria-hidden="true">
            <Icon
              name={knobs.azimuth === "ok" ? "check" : (knobs.azimuth === "east") === eastRight ? "right" : "left"} />
          </span>
          <div>
            <p class="instruction">
              {knobs.azimuth === "ok"
                ? t.polar.azimuthOk
                : (knobs.azimuth === "east" ? t.polar.turnEast : t.polar.turnWest)(formatAngle(knobs.azimuthBy, locale))}
            </p>
            <p class="caption muted">{t.polar.azimuthKnob}</p>
          </div>
        </li>
      </ul>
      <p class="caption muted">
        {#if latest?.failure}{t.polar.notSolved}{:else if moved}{moved}{:else}{t.polar.firstFrame}{/if}
        {#if latest}· {t.polar.updated(formatTime(latest.taken, locale))}{/if}
      </p>
    {:else if shown.phase}
      <section class="progress" aria-live="polite">
        <div class="bar"><span style:width="100%"></span></div>
        <p class="body">{t.polar.phase[shown.phase]}</p>
      </section>
    {/if}

    <p class="caption muted mono">{above(shown.axis)} · {eastOf(shown.axis)}</p>
    {#if shown.rotation.length}
      <p class="caption muted">{t.polar.turned(shown.rotation.map((r) => degrees(r)).join(", "))}</p>
    {/if}
    {#if shown.warning}<Banner icon="alert" tone="warning">{shown.warning}</Banner>{/if}

    <div class="actions">
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      {#if shown.phase === "adjusting"}
        <Button
          variant="primary"
          wide
          busy={busy === "finish" || finishing === shown.job}
          disabled={!auth.owner || busy !== null || finishing === shown.job}
          onclick={() => void act("finish", async () => {
            await finishPolarAlign();
            finishing = shown.job;
          })}>
          {t.polar.finish}
        </Button>
        <p class="caption muted">
          {finishing === shown.job ? t.polar.finishing : shown.options.back ? t.polar.finishBack : t.polar.finishHere}
        </p>
      {/if}
      <Button wide busy={busy === "stop"} disabled={!auth.owner} onclick={() => void act("stop", () => cancelJob(shown.job))}>
        {t.polar.stop}
      </Button>
      <p class="caption muted">{t.polar.stopHint}</p>
    </div>
  {:else}
    <section class="result">
      {#if shown.state === "succeeded" && shown.axis}
        <Chip tone={shown.aligned ? "ok" : "warning"}>
          {(shown.aligned ? t.polar.resultAligned : t.polar.resultOff)(formatAngle(shown.axis.total, locale))}
        </Chip>
        <p class="body mono">{above(shown.axis)}</p>
        <p class="body mono">{eastOf(shown.axis)}</p>
        <p class="caption muted">{shown.options.back ? t.polar.backAtStart : t.polar.stayed}</p>
      {:else}
        <Chip tone={shown.state === "cancelled" ? "neutral" : "error"}>
          {shown.state === "cancelled" ? t.polar.cancelled : t.polar.failed}
        </Chip>
        {#if shown.error}<p class="body">{shown.error}</p>{/if}
        {#if shown.axis}
          <p class="body mono">{t.polar.lastError(formatAngle(shown.axis.total, locale))}</p>
          <p class="caption muted mono">{above(shown.axis)} · {eastOf(shown.axis)}</p>
        {/if}
        <p class="caption muted">{t.polar.stoppedHere}</p>
      {/if}
    </section>
    <div class="actions">
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <Button variant="primary" wide onclick={again}>{t.polar.again}</Button>
      <Button wide onclick={close}>{t.polar.done}</Button>
    </div>
  {/if}
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
  .steps {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .steps li {
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--line);
  }
  .steps .done {
    background: var(--muted);
  }
  .steps .current {
    background: var(--accent);
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
  .last {
    margin: 0;
  }
  .start {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .start h2,
  .start p {
    margin: 0;
  }
  .settings,
  .group,
  .actions,
  .result,
  .progress {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .settings {
    gap: var(--space-4);
  }
  .result {
    align-items: flex-start;
  }
  .result p,
  .progress p,
  .actions p,
  .flow > p {
    margin: 0;
  }
  .disclosure {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .points,
  .knobs {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .points li,
  .knobs li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--raised);
  }
  .points p,
  .knobs p {
    margin: 0;
  }
  .marker,
  .knob-icon {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border: 1px solid var(--line);
    border-radius: var(--radius-full);
    font-weight: 600;
  }
  .points .current .marker {
    border-color: var(--accent);
    color: var(--accent);
  }
  .points .solved .marker,
  .knobs .ok .knob-icon {
    border-color: var(--ok);
    color: var(--ok);
  }
  .knob-icon {
    width: 44px;
    height: 44px;
    color: var(--accent);
    border-color: var(--accent);
  }
  .instruction {
    font-size: 20px;
    line-height: 26px;
    font-weight: 600;
  }
  .error-line {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
  }
  .total {
    font-size: 34px;
    line-height: 40px;
    font-weight: 600;
  }
  .bar {
    height: 8px;
    overflow: hidden;
    border-radius: var(--radius-full);
    background: var(--raised);
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 0.3s;
  }
  @media (min-width: 768px) {
    .readouts {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
  }
</style>
