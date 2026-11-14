<script lang="ts">
  // The focuser's calibration as a full-screen flow (docs/ux.md §2, ADR 0044): what
  // it does and the last one, then the measurements as they come, then the backlash
  // each way, the overshoot it set and the focuser's scale. The job belongs to the
  // server: any client that opens this screen while one runs follows it.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import Icon from "../../components/Icon.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import { cancelJob, disableDriverBacklash, getProfile, putProfile, startFocusCalibration } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { calibratedFor, unsteady } from "../../lib/focus";
  import { formatDateTime, formatDecimal, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { Profile } from "../../lib/types";
  import VCurve from "./VCurve.svelte";

  let { offline = false }: { offline?: boolean } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const run = $derived(live.app.focus_calibration ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const autofocus = $derived(live.app.autofocus ?? null);
  const running = $derived(run?.state === "running");
  const job = $derived(run ? (live.app.jobs?.[run.job] ?? null) : null);
  const profileId = $derived(live.app.equipment?.active ?? null);
  const calibration = $derived(focuser?.calibration ?? null);

  // The calibration this screen shows: the one running, or the one it started or
  // watched until the user asks for another.
  let watched = $state<string | null>(null);
  $effect(() => {
    if (run && running) watched = run.job;
  });
  const shown = $derived(run && (running || watched === run.job) ? run : null);
  const stage = $derived(!shown ? 1 : running ? 2 : 3);

  function close(): void {
    router.back({ screen: "rig" });
  }

  // -- Start ------------------------------------------------------------------------

  // Autofocus's step comes from the imaging train's sweep, as saved.
  let profile = $state<Profile | null>(null);
  $effect(() => {
    const id = profileId;
    if (!id) return;
    getProfile(id)
      .then((loaded) => {
        profile = loaded;
        untrack(() => {
          if (step === null) step = loaded.imaging?.autofocus?.step ?? autofocus?.suggested_step ?? autofocus?.step ?? null;
          form += 1;
        });
      })
      .catch(() => (profile = null));
  });
  let step = $state<number | null>(untrack(() => live.app.autofocus?.suggested_step ?? live.app.autofocus?.step ?? null));
  let form = $state(0);

  const busyJob = $derived(holder(live.app.jobs, "focuser") ?? holder(live.app.jobs, "main_camera"));
  const blocked = $derived.by(() => {
    if (!auth.owner) return t.focusCalibration.observer;
    if (!focuser || !camera) return t.autofocus.noRig;
    if (busyJob) return t.autofocus.busy;
    if (step === null) return t.focusCalibration.needStep;
    return "";
  });

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

  function start(): void {
    void act(async () => {
      watched = await startFocusCalibration({ step });
    });
  }

  function turnOff(): void {
    void act(() => disableDriverBacklash());
  }

  // -- Measuring and the result -------------------------------------------------------

  const progress = $derived(running ? (job?.progress ?? null) : null);
  // While it focuses, autofocus's own run is the one to watch.
  const focusing = $derived(running && shown?.phase === "focusing" && autofocus?.state === "running" ? autofocus : null);
  const inward = $derived(shown?.reversals.filter((r) => r.towards === "inward").map((r) => r.lost) ?? []);
  const outward = $derived(shown?.reversals.filter((r) => r.towards === "outward").map((r) => r.lost) ?? []);
  const isUnsteady = $derived(
    shown?.min_step != null && (unsteady(inward, shown.min_step) || unsteady(outward, shown.min_step)),
  );
  const suggested = $derived.by(() => {
    const value = shown?.state === "succeeded" ? shown.suggested_step : null;
    const saved = profile?.imaging?.autofocus?.step ?? null;
    if (value === null || value === undefined) return null;
    return saved === null || Math.abs(value - saved) / saved > 0.15 ? value : null;
  });

  function useStep(value: number): void {
    void act(async () => {
      if (!profile?.imaging || !profileId) return;
      const sweep = { ...(profile.imaging.autofocus ?? {}), step: value };
      const updated: Profile = { ...profile, imaging: { ...profile.imaging, autofocus: sweep } };
      await putProfile(profileId, updated);
      profile = updated;
      step = value;
    });
  }

  function again(): void {
    watched = null;
    error = "";
  }

  function list(values: readonly number[]): string {
    return values.length ? values.map((v) => formatPlain(v, locale)).join(" · ") : "—";
  }

  function number(value: number | null | undefined, digits?: number): string {
    if (value === null || value === undefined) return "—";
    return digits === undefined ? formatPlain(value, locale) : formatDecimal(value, locale, digits);
  }
</script>

<main class="flow">
  <header class="header">
    <button type="button" class="close" aria-label={t.focusCalibration.close} onclick={close}>
      <Icon name="close" />
    </button>
    <div class="titles">
      <p class="caption muted">{t.autofocus.stepOf(stage, 3)} · {t.focusCalibration.steps[stage - 1]}</p>
      <h1 class="title">{t.focusCalibration.title}</h1>
    </div>
    <ThemeButton />
  </header>
  <ol class="steps" aria-hidden="true">
    {#each t.focusCalibration.steps as name, i (name)}
      <li class:done={i + 1 < stage} class:current={i + 1 === stage}></li>
    {/each}
  </ol>

  {#if offline}<Banner icon="offline" tone="warning">{t.link.offline}</Banner>{/if}

  {#if !shown}
    <section class="text">
      <p class="body">{t.focusCalibration.intro}</p>
      <p class="body muted">{t.focusCalibration.needs}</p>
      {#if calibration}
        <p class="body">
          {calibratedFor(calibration, profileId)
            ? t.focusCalibration.calibrated(formatDateTime(calibration.measured, locale), calibration.profile ?? "—")
            : t.focusCalibration.otherProfile(calibration.profile ?? "—")}
        </p>
        <section class="readouts">
          <div>
            <span class="label muted">{t.focusCalibration.inward}</span>
            <span class="readout mono">{list(calibration.inward)}</span>
          </div>
          <div>
            <span class="label muted">{t.focusCalibration.outward}</span>
            <span class="readout mono">{list(calibration.outward)}</span>
          </div>
          <div>
            <span class="label muted">{t.focusCalibration.overshoot}</span>
            <span class="readout mono">{number(calibration.overshoot)}</span>
          </div>
          <div>
            <span class="label muted">{t.focusCalibration.zone}</span>
            <span class="readout mono">{number(calibration.focus_zone)}</span>
          </div>
        </section>
      {:else}
        <p class="body muted">{t.focusCalibration.never}</p>
      {/if}
    </section>

    {#if focuser?.driver_backlash != null}
      <p class="body muted">{t.focusCalibration.driver(formatPlain(focuser.driver_backlash, locale))}</p>
    {/if}

    {#key form}
      <Stepper
        label={t.focusCalibration.step}
        bind:value={step}
        min={1}
        max={focuser?.max_position ?? 100000}
        step={step !== null && step >= 1000 ? 100 : 10}
        hint={t.focusCalibration.stepHint} />
    {/key}

    <div class="actions">
      {#if blocked}<p class="caption muted">{blocked}</p>{/if}
      <SequenceHold resources={["focuser", "main_camera"]} />
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <Button variant="primary" wide {busy} disabled={!!blocked} onclick={start}>{t.focusCalibration.start}</Button>
    </div>
  {:else}
    {#if focusing}
      <VCurve
        points={focusing.points}
        fit={focusing.fit}
        position={focuser?.position ?? null}
        best={focusing.fit ? Math.round(focusing.fit.c) : null}
        expected={[focusing.start_position - 4 * focusing.step, focusing.start_position + 4 * focusing.step]} />
    {/if}

    {#if shown.reversals.length || shown.trips.length}
      <ul class="log">
        {#each shown.reversals as r, i (i)}
          <li class="body mono">{t.focusCalibration.lost(t.focusCalibration.towards[r.towards], formatPlain(r.lost, locale))}</li>
        {/each}
        {#each shown.trips as trip, i (i)}
          <li class="body mono">{t.focusCalibration.trip(formatPlain(trip.target, locale), trip.ok)}</li>
        {/each}
      </ul>
    {/if}

    {#if running}
      <section class="progress" aria-live="polite">
        <div class="bar" role="progressbar" aria-valuemin={0} aria-valuemax={1} aria-valuenow={progress ?? undefined}>
          <span style:width="{Math.round((progress ?? 0) * 100)}%"></span>
        </div>
        <p class="body">{shown.phase ? t.focusCalibration.phase[shown.phase] : ""}</p>
      </section>
      <div class="actions">
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="danger" wide {busy} disabled={!auth.owner} onclick={() => void act(() => cancelJob(shown.job))}>
          {t.focusCalibration.cancel}
        </Button>
        <p class="caption muted">{t.focusCalibration.cancelHint}</p>
      </div>
    {:else}
      <section class="result">
        {#if shown.state === "succeeded"}
          <Chip tone="ok">{t.focusCalibration.succeeded}</Chip>
          <section class="readouts">
            <div>
              <span class="label muted">{t.focusCalibration.inward}</span>
              <span class="readout mono">{list(inward)}</span>
            </div>
            <div>
              <span class="label muted">{t.focusCalibration.outward}</span>
              <span class="readout mono">{list(outward)}</span>
            </div>
            <div>
              <span class="label muted">{t.focusCalibration.overshoot}</span>
              <span class="readout mono">{number(shown.overshoot)}</span>
            </div>
            <div>
              <span class="label muted">{t.focusCalibration.minStep}</span>
              <span class="readout mono">{number(shown.min_step)}</span>
            </div>
            <div>
              <span class="label muted">{t.focusCalibration.microns}</span>
              <span class="readout mono">
                {shown.microns_per_step === null ? "—" : t.focusCalibration.micronsValue(number(shown.microns_per_step, 2))}
              </span>
            </div>
            <div>
              <span class="label muted">{t.focusCalibration.zone}</span>
              <span class="readout mono">
                {shown.focus_zone === null ? "—" : t.focusCalibration.stepsValue(number(shown.focus_zone))}
              </span>
            </div>
          </section>
          {#if shown.overshoot !== null}
            <p class="body">{t.focusCalibration.overshootApplied(formatPlain(shown.overshoot, locale))}</p>
          {/if}
          {#if shown.driver_backlash !== null}
            <p class="body muted">{t.focusCalibration.driverTurnedOff(formatPlain(shown.driver_backlash, locale))}</p>
          {/if}
          {#if isUnsteady}<Banner icon="alert" tone="warning">{t.focusCalibration.unsteady}</Banner>{/if}
          {#if shown.slip}<Banner icon="alert" tone="warning">{t.focusCalibration.slip}</Banner>{/if}
          {#if suggested !== null}
            <p class="body">{t.focusCalibration.suggest(formatPlain(suggested, locale))}</p>
            {#if auth.owner && profile?.imaging}
              <Button variant="text" {busy} onclick={() => useStep(suggested)}>{t.focusCalibration.useStep}</Button>
            {/if}
          {/if}
        {:else}
          <Chip tone={shown.state === "cancelled" ? "neutral" : "error"}>
            {shown.state === "cancelled" ? t.focusCalibration.cancelled : t.focusCalibration.failed}
          </Chip>
          {#if shown.problem}
            <p class="body">{t.focusCalibration.problem[shown.problem]}</p>
            {#if shown.problem === "autofocus" && autofocus?.problem}
              <p class="body">{t.autofocus.problem[autofocus.problem]}</p>
            {/if}
            {#if shown.problem === "driver_backlash" && auth.owner && focuser?.driver_backlash != null}
              <Button {busy} onclick={turnOff}>{t.focusCalibration.turnOff}</Button>
            {/if}
          {/if}
          {#if shown.detail}<p class="caption muted">{shown.detail}</p>{/if}
          {#if shown.best}
            <p class="caption muted">{t.autofocus.back(formatPlain(shown.best.position, locale))}</p>
          {/if}
        {/if}
      </section>
      <div class="actions">
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="primary" wide onclick={again}>{t.focusCalibration.again}</Button>
        <Button wide onclick={close}>{t.focusCalibration.done}</Button>
      </div>
    {/if}
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
    grid-template-columns: repeat(3, 1fr);
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
  .text,
  .actions,
  .result,
  .progress {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .result {
    align-items: flex-start;
  }
  .result .readouts {
    align-self: stretch;
  }
  .text p,
  .result p,
  .progress p,
  .actions p {
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
  .log {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
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
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }
</style>
