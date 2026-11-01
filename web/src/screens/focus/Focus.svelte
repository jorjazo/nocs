<script lang="ts">
  // Autofocus as a full-screen flow (docs/ux.md §1–2, ADR 0021): settings, then
  // the sweep with its live V-curve, then the result or why it failed. The run
  // belongs to the server: any client that opens this screen while one runs
  // follows it, and cancelling takes the focuser back to where it started.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import Icon from "../../components/Icon.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import {
    autofocusRuns,
    cancelJob,
    getProfile,
    putProfile,
    setFocuserBacklash,
    startAutofocus,
  } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain, formatTemperature, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { AutofocusState, FocusSweep, Profile } from "../../lib/types";
  import { estimateStep } from "../../lib/focus";
  import VCurve from "./VCurve.svelte";

  let { offline = false }: { offline?: boolean } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const run = $derived(live.app.autofocus ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const running = $derived(run?.state === "running");
  const job = $derived(run ? (live.app.jobs?.[run.job] ?? null) : null);

  // The run this screen shows: the one running, or the one it started or
  // watched until the user asks for another. Opening the screen later shows
  // the settings, with the last run summed up.
  let watched = $state<string | null>(null);
  $effect(() => {
    if (run && running) watched = run.job;
  });
  const shown = $derived(run && (running || watched === run.job) ? run : null);
  const step = $derived(!shown ? 1 : running ? 2 : 3);

  function close(): void {
    router.back({ screen: "live" });
  }

  // -- Settings ---------------------------------------------------------------------

  // The imaging train's sweep comes from the profile as saved.
  let profile = $state<Profile | null>(null);
  const profileId = $derived(live.app.equipment?.active ?? null);
  let profileTried = $state(false);
  $effect(() => {
    const id = profileId;
    if (!id) {
      profileTried = true;
      return;
    }
    getProfile(id)
      .then((loaded) => {
        profile = loaded;
        untrack(() => adopt(loaded.imaging?.autofocus ?? null));
      })
      .catch(() => (profile = null))
      .finally(() => (profileTried = true));
  });

  let sweepStep = $state<number | null>(untrack(() => live.app.autofocus?.step ?? null));
  let points = $state(9);
  let exposure = $state<number | null>(2);
  let exposureValid = $state(true);
  let frames = $state(1);
  let remember = $state(true);
  let advanced = $state(false);
  let direction = $state<"outward" | "inward">(untrack(() => live.app.focuser?.backlash.direction ?? "outward"));
  let overshoot = $state<number | null>(untrack(() => live.app.focuser?.backlash.overshoot ?? null));
  let overshootValid = $state(true);

  // The fields read their value when they mount: they are mounted again when
  // the profile's sweep arrives.
  let form = $state(0);

  function adopt(sweep: FocusSweep | null): void {
    if (!sweep) return;
    prefilled = null;
    sweepStep = sweep.step;
    points = sweep.points ?? 9;
    exposure = sweep.exposure ?? 2;
    frames = sweep.frames ?? 1;
    form += 1;
  }

  // The last run, also after nocsd restarted (the state starts empty).
  let lastSaved = $state<AutofocusState | null>(null);
  let lastTried = $state(false);
  $effect(() => {
    autofocusRuns(1)
      .then((runs) => (lastSaved = runs[0]?.run ?? null))
      .catch(() => {})
      .finally(() => (lastTried = true));
  });
  const last = $derived(run && !running ? run : lastSaved);

  // Without a step in the profile, the last run's (or the one it suggested), or
  // else one estimated from the focuser's travel and the f-ratio: a first night
  // starts with something to try rather than an empty field.
  const focalRatio = $derived.by(() => {
    const optics = profile?.imaging;
    if (!optics?.aperture) return null;
    return (optics.focal_length * (optics.reducer ?? 1)) / optics.aperture;
  });
  let prefilled = $state<"last" | "estimate" | null>(null);
  $effect(() => {
    if (sweepStep !== null || !profileTried || !lastTried) return;
    const previous = last?.suggested_step ?? last?.step ?? null;
    const estimate = estimateStep(focuser?.max_position ?? null, focalRatio);
    const value = previous ?? estimate;
    if (value === null) return;
    untrack(() => {
      sweepStep = value;
      prefilled = previous !== null ? "last" : "estimate";
      form += 1;
    });
  });
  const temperatureChange = $derived.by(() => {
    const now = focuser?.temperature ?? null;
    const then = last?.temperature ?? null;
    if (now === null || then === null || Math.abs(now - then) < 0.1) return null;
    const degrees = formatTemperature(Math.abs(now - then), locale);
    return now > then ? t.autofocus.warmer(degrees) : t.autofocus.colder(degrees);
  });

  const busyJob = $derived(holder(live.app.jobs, "focuser") ?? holder(live.app.jobs, "main_camera"));
  const blocked = $derived.by(() => {
    if (!auth.owner) return t.autofocus.observer;
    if (!focuser || !camera) return t.autofocus.noRig;
    if (busyJob) return t.autofocus.busy;
    if (sweepStep === null) return t.autofocus.needStep;
    return "";
  });
  const valid = $derived(exposureValid && overshootValid && exposure !== null);
  const canRemember = $derived(profile !== null && !!profile.imaging);

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

  function sweepSettings(): FocusSweep {
    return { step: sweepStep ?? 1, points, exposure: exposure ?? 2, frames };
  }

  async function saveSweep(sweep: FocusSweep): Promise<void> {
    if (!profile?.imaging || !profileId) return;
    const saved = profile.imaging.autofocus;
    if (
      saved &&
      saved.step === sweep.step &&
      saved.points === sweep.points &&
      saved.exposure === sweep.exposure &&
      saved.frames === sweep.frames
    ) {
      return;
    }
    const updated: Profile = { ...profile, imaging: { ...profile.imaging, autofocus: sweep } };
    await putProfile(profileId, updated);
    profile = updated;
  }

  function start(): void {
    void act(async () => {
      const sweep = sweepSettings();
      if (remember && canRemember) await saveSweep(sweep);
      const backlash = focuser?.backlash;
      if (backlash && (backlash.direction !== direction || backlash.overshoot !== overshoot)) {
        await setFocuserBacklash({ direction, overshoot });
      }
      watched = await startAutofocus({ ...sweep, direction, overshoot });
    });
  }

  // -- The run --------------------------------------------------------------------

  const measured = $derived((shown?.points ?? []).filter((p) => p.hfr !== null));
  const lowest = $derived(
    measured.reduce<(typeof measured)[number] | null>(
      (best, p) => (best === null || (p.hfr ?? Infinity) < (best.hfr ?? Infinity) ? p : best),
      null,
    ),
  );
  const best = $derived(shown?.position ?? (shown?.fit ? Math.round(shown.fit.c) : null));
  const progress = $derived(running ? (job?.progress ?? null) : null);
  const suggested = $derived.by(() => {
    const value = shown?.suggested_step ?? null;
    if (value === null || !shown) return null;
    return Math.abs(value - shown.step) / shown.step > 0.15 ? value : null;
  });

  function useSuggested(value: number): void {
    void act(async () => {
      sweepStep = value;
      await saveSweep({ ...sweepSettings(), step: value });
    });
  }

  function useOvershoot(value: number | null): void {
    if (value === null) return;
    void act(async () => {
      overshoot = value;
      await setFocuserBacklash({ direction, overshoot: value });
    });
  }

  function again(): void {
    watched = null;
    error = "";
  }

  function number(value: number | null | undefined, digits?: number): string {
    if (value === null || value === undefined) return "—";
    return digits === undefined ? formatPlain(value, locale) : formatDecimal(value, locale, digits);
  }
</script>

<main class="flow">
  <header class="header">
    <button type="button" class="close" aria-label={t.autofocus.close} onclick={close}>
      <Icon name="close" />
    </button>
    <div class="titles">
      <p class="caption muted">{t.autofocus.stepOf(step, 3)} · {t.autofocus.steps[step - 1]}</p>
      <h1 class="title">{t.autofocus.title}</h1>
    </div>
    <ThemeButton />
  </header>
  <ol class="steps" aria-hidden="true">
    {#each t.autofocus.steps as name, i (name)}
      <li class:done={i + 1 < step} class:current={i + 1 === step}></li>
    {/each}
  </ol>

  {#if offline}<Banner icon="offline" tone="warning">{t.link.offline}</Banner>{/if}

  {#if !shown}
    <section class="readouts">
      <div>
        <span class="label muted">{t.autofocus.position}</span>
        <span class="readout mono">{number(focuser?.position)}</span>
      </div>
      <div>
        <span class="label muted">{t.autofocus.focuser}</span>
        <span class="readout mono">
          {focuser?.temperature != null ? formatTemperature(focuser.temperature, locale) : "—"}
        </span>
      </div>
      <div>
        <span class="label muted">{t.autofocus.ambient}</span>
        <span class="readout mono">
          {live.app.weather?.temperature != null ? formatTemperature(live.app.weather.temperature, locale) : "—"}
        </span>
      </div>
      <div>
        <span class="label muted">{t.autofocus.filter}</span>
        <span class="readout">{live.app.filter_wheel?.filter ?? "—"}</span>
      </div>
    </section>

    {#if last}
      <p class="body muted last">
        {last.state === "succeeded" && last.position !== null
          ? t.autofocus.last(formatTime(last.started, locale), formatPlain(last.position, locale))
          : t.autofocus.lastFailed(formatTime(last.started, locale))}
        {#if temperatureChange}{t.autofocus.since(temperatureChange)}{/if}
      </p>
    {/if}

    {#key form}
    <section class="settings">
      <Stepper
        label={t.autofocus.step}
        bind:value={sweepStep}
        min={1}
        max={focuser?.max_position ?? 100000}
        step={sweepStep !== null && sweepStep >= 1000 ? 100 : 10}
        hint={prefilled === "estimate" && focalRatio !== null
          ? t.autofocus.stepEstimated(formatDecimal(focalRatio, locale, 1))
          : prefilled === "last"
            ? t.autofocus.stepFromLast
            : t.autofocus.stepHint} />
      <div class="group">
        <span class="label muted">{t.autofocus.points}</span>
        <SegmentedControl
          label={t.autofocus.points}
          options={[7, 9, 11, 13].map((n) => ({ value: String(n), label: String(n) }))}
          value={String(points)}
          onchange={(value) => (points = Number(value))} />
      </div>
      <NumberField label={t.autofocus.exposure} bind:value={exposure} bind:valid={exposureValid} min={0.01} max={600} unit="s" />

      <button type="button" class="disclosure" aria-expanded={advanced} onclick={() => (advanced = !advanced)}>
        <Icon name={advanced ? "chevronDown" : "chevronRight"} size={20} />
        {t.autofocus.advanced}
      </button>
      {#if advanced}
        <div class="group">
          <span class="label muted">{t.autofocus.frames}</span>
          <SegmentedControl
            label={t.autofocus.frames}
            options={[1, 2, 3].map((n) => ({ value: String(n), label: String(n) }))}
            value={String(frames)}
            onchange={(value) => (frames = Number(value))} />
        </div>
        <div class="group">
          <span class="label muted">{t.autofocus.direction}</span>
          <SegmentedControl
            label={t.autofocus.direction}
            options={[
              { value: "outward", label: t.autofocus.outward },
              { value: "inward", label: t.autofocus.inward },
            ]}
            value={direction}
            onchange={(value) => (direction = value === "inward" ? "inward" : "outward")} />
        </div>
        <NumberField
          label={t.autofocus.overshoot}
          bind:value={overshoot}
          bind:valid={overshootValid}
          min={0}
          max={100000}
          hint={t.autofocus.overshootHint}
          placeholder={sweepStep !== null ? formatPlain(sweepStep, locale) : ""} />
        {#if canRemember}
          <Toggle
            label={t.autofocus.remember}
            hint={t.autofocus.rememberHint}
            checked={remember}
            onchange={(value) => (remember = value)} />
        {/if}
      {/if}
    </section>
    {/key}

    <div class="actions">
      {#if blocked}<p class="caption muted">{blocked}</p>{/if}
      <SequenceHold resources={["focuser", "main_camera"]} />
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <Button variant="primary" wide {busy} disabled={!!blocked || !valid} onclick={start}>
        {t.autofocus.start}
      </Button>
    </div>
  {:else}
    {#if running || shown.points.length > 0}
      <VCurve
        points={shown.points}
        fit={shown.fit}
        position={running ? (focuser?.position ?? null) : null}
        {best}
        expected={[shown.start_position - 4 * shown.step, shown.start_position + 4 * shown.step]} />

      <section class="readouts">
        <div>
          <span class="label muted">{t.autofocus.best}</span>
          <span class="readout mono">{number(best ?? lowest?.position)}</span>
        </div>
        <div>
          <span class="label muted">{t.autofocus.hfr}</span>
          <span class="readout mono">{number(shown.hfr ?? lowest?.hfr, 2)}</span>
        </div>
        <div>
          <span class="label muted">{t.autofocus.stars}</span>
          <span class="readout mono">{number(shown.stars ?? lowest?.stars)}</span>
        </div>
        <div>
          <span class="label muted">{t.autofocus.focuser}</span>
          <span class="readout mono">
            {focuser?.temperature != null ? formatTemperature(focuser.temperature, locale) : "—"}
          </span>
        </div>
      </section>
    {/if}

    {#if running}
      <section class="progress" aria-live="polite">
        <div class="bar" role="progressbar" aria-valuemin={0} aria-valuemax={1} aria-valuenow={progress ?? undefined}>
          <span style:width="{Math.round((progress ?? 0) * 100)}%"></span>
        </div>
        <p class="body">{shown.phase ? t.autofocus.phase[shown.phase] : ""}</p>
        <p class="caption muted mono">{t.autofocus.step} {formatPlain(shown.step, locale)}</p>
      </section>
      <div class="actions">
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="danger" wide {busy} disabled={!auth.owner} onclick={() => void act(() => cancelJob(shown.job))}>
          {t.autofocus.cancel}
        </Button>
        <p class="caption muted">{t.autofocus.cancelHint}</p>
      </div>
    {:else}
      <section class="result">
        {#if shown.state === "succeeded" && shown.position !== null}
          <Chip tone="ok">{t.autofocus.focused(formatPlain(shown.position, locale))}</Chip>
          {#if shown.start_hfr !== null && shown.hfr !== null}
            <p class="body mono">{t.autofocus.hfrChange(number(shown.start_hfr, 2), number(shown.hfr, 2))}</p>
          {/if}
          {#if shown.fit}<p class="caption muted mono">{t.autofocus.fit(number(shown.fit.r_squared, 3))}</p>{/if}
          {#if suggested !== null}
            <p class="body">{t.autofocus.suggest(formatPlain(suggested, locale))}</p>
            {#if canRemember && auth.owner}
              <Button variant="text" {busy} onclick={() => useSuggested(suggested)}>{t.autofocus.useStep}</Button>
            {/if}
          {/if}
        {:else}
          <Chip tone={shown.state === "cancelled" ? "neutral" : "error"}>
            {shown.state === "cancelled" ? t.autofocus.cancelled : t.autofocus.failed}
          </Chip>
          {#if shown.problem}
            <p class="body">{t.autofocus.problem[shown.problem]}</p>
            {#if shown.suggested_overshoot}
              <p class="body">{t.autofocus.suggestOvershoot(formatPlain(shown.suggested_overshoot, locale))}</p>
              {#if auth.owner}
                <Button variant="text" {busy} onclick={() => useOvershoot(shown.suggested_overshoot ?? null)}
                  >{t.autofocus.useOvershoot}</Button
                >
              {/if}
            {/if}
          {:else if shown.detail}
            <p class="body">{shown.detail}</p>
          {/if}
          <p class="caption muted">{t.autofocus.back(formatPlain(shown.start_position, locale))}</p>
        {/if}
      </section>
      <div class="actions">
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="primary" wide onclick={again}>{t.autofocus.again}</Button>
        <Button wide onclick={close}>{t.autofocus.done}</Button>
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
  .actions p {
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
