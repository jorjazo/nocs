<script lang="ts">
  // The flats wizard as a full-screen flow (ADR 0036): the light (a panel or the
  // twilight sky), the filters and how many flats each, the level; then each
  // filter's progress. NOCS finds every exposure itself. Opened from a night's
  // calibration it takes that night's filters, gain, offset, binning and focus.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import Icon from "../../components/Icon.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { cancelJob, flatWindows, getCalibration, startFlats } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatPlain, formatSeconds, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { CalibrationGroup, FlatPlan, FlatWindows } from "../../lib/types";

  let { offline, night }: { offline: boolean; night: number | null } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const FULL = 65535;

  type Row = { filter: string | null; count: number | null; focus: number | null; on: boolean };

  let source = $state<"panel" | "sky">("panel");
  let rows = $state<Row[]>([]);
  let level = $state<number | null>(50);
  let advanced = $state(false);
  let minExposure = $state<number | null>(0.01);
  let maxExposure = $state<number | null>(60);
  let setup = $state<CalibrationGroup["setup"] | null>(null);
  let windows = $state<FlatWindows | null>(null);
  let windowError = $state("");
  let error = $state("");
  let busy = $state(false);
  let started = $state(false);

  const flats = $derived(live.app.flats ?? null);
  const job = $derived(
    Object.entries(live.app.jobs ?? {}).find(([, j]) => j.kind === "flats" && j.state === "running")?.[0] ?? null,
  );
  // The run shows once this screen started one, or while any runs.
  const shown = $derived(flats !== null && (job !== null || started));

  // The filters: the night's lights' (with their focus), or the wheel's.
  $effect(() => {
    if (rows.length > 0) return;
    if (night !== null) {
      void fromNight(night);
    } else {
      const names = (live.app.filter_wheel?.names ?? []).filter((n) => n.trim());
      rows = names.length ? names.map((n) => ({ filter: n, count: 20, focus: null, on: true })) : [{ filter: null, count: 20, focus: null, on: true }];
    }
  });

  async function fromNight(id: number): Promise<void> {
    try {
      const report = await getCalibration({ night: id });
      const byFilter = new Map<string | null, Row>();
      for (const g of report.groups) {
        if (!byFilter.has(g.filter)) {
          const missing = report.needs.find((n) => n.kind === "flat" && n.filter === g.filter);
          byFilter.set(g.filter, { filter: g.filter, count: missing?.count ?? 20, focus: g.focus, on: missing !== undefined });
        }
      }
      rows = [...byFilter.values()];
      // The setup of lights that miss flats: a night can mix setups.
      setup = (report.needs.find((n) => n.kind === "flat") ?? report.groups[0])?.setup ?? null;
    } catch (e) {
      error = errorText(e, t);
    }
  }

  $effect(() => {
    if (source !== "sky" || windows !== null) return;
    flatWindows().then(
      (found) => (windows = found),
      (e: unknown) => (windowError = errorText(e, t)),
    );
  });

  const chosen = $derived(rows.filter((r) => r.on));
  const valid = $derived(
    chosen.length > 0 &&
      chosen.every((r) => r.count !== null) &&
      level !== null &&
      minExposure !== null &&
      maxExposure !== null &&
      minExposure < maxExposure,
  );

  async function start(): Promise<void> {
    const [first, ...others] = chosen.map((r) => ({ filter: r.filter, count: r.count ?? 20, focus: r.focus }));
    if (!valid || !first || level === null || minExposure === null || maxExposure === null) return;
    const plan: FlatPlan = {
      source,
      filters: [first, ...others],
      level: level / 100,
      min_exposure: minExposure,
      max_exposure: maxExposure,
      gain: setup?.gain ?? null,
      offset: setup?.offset ?? null,
      binning: setup?.binning ?? null,
    };
    busy = true;
    try {
      await startFlats(plan);
      started = true;
      error = "";
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  async function cancel(): Promise<void> {
    if (job === null) return;
    try {
      await cancelJob(job);
    } catch (e) {
      error = errorText(e, t);
    }
  }

  function close(): void {
    router.back({ screen: "session" });
  }

  function percent(adu: number | null): string {
    return adu === null ? "—" : `${formatPlain((adu / FULL) * 100, locale, 0)} %`;
  }

  const outcomeTone = $derived(
    flats?.state === "succeeded" ? "ok" : flats?.state === "running" ? "accent" : flats?.state === "failed" ? "error" : "neutral",
  );
</script>

<main class="flow">
  <header class="header">
    <button type="button" class="close" aria-label={t.flats.close} onclick={close}>
      <Icon name="close" />
    </button>
    <h1 class="title">{t.flats.title}</h1>
    <ThemeButton />
  </header>

  {#if offline}<Banner icon="offline" tone="warning">{t.link.offline}</Banner>{/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

  {#if shown && flats}
    <section class="run" aria-live="polite">
      <div class="state">
        <Chip tone={outcomeTone}>{t.flats.outcome[flats.state]}</Chip>
        <span class="caption muted">{flats.source === "sky" ? t.flats.sky : t.flats.panel} · {percent(flats.target)}</span>
      </div>
      {#if flats.message}<p class="body muted">{flats.message}</p>{/if}
      {#if flats.error}<Banner icon="alert" tone="error">{flats.error}</Banner>{/if}
      <ul class="filters">
        {#each flats.filters as f, i (i)}
          <li>
            <span class="name">{f.filter ?? "—"}</span>
            <span class="caption muted">
              {t.flats.progress(f.done, f.count)}
              {#if f.exposure !== null}· {formatSeconds(f.exposure, locale)}{/if}
              {#if f.level !== null}· {t.flats.at(percent(f.level))}{/if}
            </span>
            <Chip tone={f.state === "done" ? "ok" : f.state === "running" ? "accent" : f.state === "failed" ? "error" : "neutral"}>
              {t.flats.states[f.state]}
            </Chip>
            {#if f.message}<span class="caption muted message">{f.message}</span>{/if}
            <div class="bar" role="progressbar" aria-valuemin={0} aria-valuemax={f.count} aria-valuenow={f.done}>
              <span style:width={`${(f.done / f.count) * 100}%`}></span>
            </div>
          </li>
        {/each}
      </ul>
      <div class="actions">
        {#if job !== null}
          <Button wide onclick={() => void cancel()}>{t.flats.cancel}</Button>
        {:else}
          <Button variant="primary" wide onclick={() => (started = false)}>{t.flats.again}</Button>
          <Button wide onclick={close}>{t.flats.done}</Button>
        {/if}
      </div>
    </section>
  {:else}
    <SegmentedControl
      label={t.flats.source}
      options={[
        { value: "panel", label: t.flats.panel },
        { value: "sky", label: t.flats.sky },
      ]}
      value={source}
      onchange={(value) => (source = value)} />
    <p class="body muted">{source === "sky" ? t.flats.skyHint : t.flats.panelHint}</p>

    {#if source === "sky"}
      {#if windowError}
        <Banner icon="alert" tone="warning">{windowError}</Banner>
      {:else if windows}
        <section class="windows" aria-label={t.flats.windows}>
          {#each windows.windows as w (w.start)}
            <span class="tile">
              <span class="caption muted">{w.phase === "dusk" ? t.flats.dusk : t.flats.dawn}</span>
              <span class="mono">{formatTime(w.start, locale)}–{formatTime(w.end, locale)}</span>
            </span>
          {/each}
        </section>
      {/if}
    {/if}

    <section class="rows" aria-label={t.flats.filters}>
      <h2 class="heading">{t.flats.filters}</h2>
      {#each rows as row, i (i)}
        <div class="row">
          <Toggle
            label={row.filter ?? "—"}
            hint={row.focus !== null ? t.flats.focus(formatPlain(row.focus, locale)) : undefined}
            checked={row.on}
            onchange={(on) => (row.on = on)} />
          {#if row.on}
            <Stepper label={t.flats.count} bind:value={row.count} min={1} max={200} />
          {/if}
        </div>
      {/each}
    </section>

    <Stepper label={t.flats.level} hint={t.flats.levelHint} bind:value={level} min={10} max={90} step={5} unit="%" />
    {#if setup}<p class="caption muted">{t.flats.fromLights}</p>{/if}

    <Toggle label={t.flats.advanced} checked={advanced} onchange={(on) => (advanced = on)} />
    {#if advanced}
      <NumberField label={t.flats.minExposure} bind:value={minExposure} min={0.001} max={60} unit="s" />
      <NumberField label={t.flats.maxExposure} bind:value={maxExposure} min={0.01} max={600} unit="s" />
    {/if}

    <div class="actions">
      <Button variant="primary" wide {busy} disabled={!valid || !auth.owner || job !== null} onclick={() => void start()}>
        {t.flats.start}
      </Button>
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
  .title {
    margin: 0;
  }
  .rows,
  .run {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .windows {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
  }
  .state {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .filters {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .filters li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    font-weight: 600;
  }
  .message,
  .bar {
    grid-column: 1 / -1;
  }
  .bar {
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--line);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .actions {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
