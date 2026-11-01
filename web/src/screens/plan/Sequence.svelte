<script lang="ts">
  // Plan → Sequence (stage 5.13): "this target, these filters, tonight". The
  // builder edits a template for tonight's target (one sequence per target),
  // shows what it costs and how much of tonight it has, saves it and starts it.
  // The steps the template makes are read only, under Advanced (ADR 0031).
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { estimateTemplate, expandTemplate, saveTemplate, startSequence } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatBytes, formatDuration, formatSeconds, formatTemperature, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import {
    builder,
    endSummary,
    focusSummary,
    isActive,
    nextFilter,
    rowSeconds,
    windowSummary,
  } from "../../lib/sequence.svelte";
  import type { PlanRow, Sequence, SequenceEstimate } from "../../lib/types";
  import PlanSwitch from "./PlanSwitch.svelte";
  import RowSheet from "./RowSheet.svelte";
  import SequenceSheets, { type SheetKind } from "./SequenceSheets.svelte";
  import SequenceSteps from "./SequenceSteps.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const planned = $derived(live.app.plan?.target ?? null);
  const wheel = $derived(live.app.filter_wheel ?? null);
  const filters = $derived((wheel?.names ?? []).filter((name) => name));
  const outputs = $derived(live.app.power?.outputs ?? []);
  const camera = $derived(live.app.cameras?.main ?? null);
  const running = $derived(isActive(live.app.sequence?.run) ? live.app.sequence?.run : null);
  // The profile has a guide camera: PHD2 is connected when the sequence starts guiding.
  const canGuide = $derived(!!live.app.equipment?.devices.guide_camera);

  // Tonight's target decides what the builder edits.
  $effect(() => {
    const target = planned;
    if (!target || !auth.owner) return;
    const draft = builder.draft;
    if (draft && draft.target.name === target.name && draft.target.ra === target.ra && draft.target.dec === target.dec) {
      return;
    }
    void builder.open(target, wheel?.filter ?? filters[0] ?? null, canGuide);
  });

  const draft = $derived(builder.draft);

  let estimate = $state<SequenceEstimate | null>(null);
  let steps = $state<Sequence | null>(null);
  let problem = $state("");
  let advanced = $state(false);
  let error = $state("");
  let busy: "save" | "start" | null = $state(null);
  let editing: number | null = $state(null);
  let sheet: SheetKind | null = $state(null);

  // What the plan costs, and the steps it makes, a moment after each change.
  let asked = 0;
  $effect(() => {
    if (!draft) return;
    const body = $state.snapshot(draft);
    const withSteps = advanced;
    const id = ++asked;
    const timer = setTimeout(() => {
      estimateTemplate(body)
        .then((found) => {
          if (id !== asked) return;
          estimate = found;
          problem = "";
        })
        .catch((e) => {
          if (id === asked) problem = errorText(e, t);
        });
      if (withSteps) {
        expandTemplate(body)
          .then((found) => {
            if (id === asked) steps = found;
          })
          .catch(() => {});
      }
    }, 300);
    return () => clearTimeout(timer);
  });

  const destination = $derived.by(() => {
    const storage = live.app.storage;
    return storage?.destinations.find((d) => d.id === storage.destination) ?? null;
  });
  const fits = $derived(estimate?.window == null || estimate.window >= estimate.duration);

  function filterLabel(row: PlanRow): string {
    return row.filter ?? t.sequence.noFilter;
  }

  function changeCount(index: number, by: number): void {
    const row = draft?.rows[index];
    if (row) row.count = Math.min(10000, Math.max(1, row.count + by));
  }

  function addRow(): void {
    if (!draft) return;
    const last = draft.rows.at(-1);
    draft.rows.push({
      filter: filters.length ? nextFilter(draft.rows, filters) : null,
      exposure: last?.exposure ?? 120,
      count: last?.count ?? 20,
    });
    editing = draft.rows.length - 1;
  }

  async function save(): Promise<string | null> {
    const id = builder.id;
    if (!draft || !id) return null;
    await saveTemplate(id, $state.snapshot(draft));
    builder.markSaved();
    return id;
  }

  async function run(what: "save" | "start"): Promise<void> {
    busy = what;
    error = "";
    try {
      const id = await save();
      if (what === "start" && id) {
        await startSequence(id);
        router.go({ screen: "session" });
      }
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

<ScreenHeader title={t.tabs.plan}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

<div class="screen">
  <PlanSwitch value="sequence" />

  {#if !auth.owner}
    <EmptyState icon="plan" title={t.sequence.ownerOnly} body="" />
  {:else if !planned}
    <EmptyState icon="plan" title={t.sequence.noTarget} body={t.sequence.noTargetBody}>
      {#snippet action()}
        <Button variant="primary" onclick={() => router.go({ screen: "plan" })}>{t.sequence.findTarget}</Button>
      {/snippet}
    </EmptyState>
  {:else if !draft}
    <p class="muted" role="status">{t.sequence.loading}</p>
  {:else}
    {#if running}
      <Banner icon="session">
        {t.sequence.running}
        {#snippet action()}
          <Button variant="text" onclick={() => router.go({ screen: "session" })}>{t.sequence.openSession}</Button>
        {/snippet}
      </Banner>
    {/if}

    <section class="card target">
      <span class="text">
        <span class="name">{draft.target.name}</span>
        <span class="muted small">{windowSummary(draft, t, locale)}</span>
      </span>
      <Button variant="text" onclick={() => router.go({ screen: "plan" })}>{t.sequence.change}</Button>
    </section>

    <section aria-labelledby="exposures">
      <div class="heading">
        <h2 id="exposures">{t.sequence.exposures}</h2>
        <Button variant="text" onclick={addRow}>{t.sequence.addFilter}</Button>
      </div>
      <ul class="rows">
        {#each draft.rows as row, i (i)}
          <li>
            <button type="button" class="row-main" aria-label={t.sequence.edit(filterLabel(row))} onclick={() => (editing = i)}>
              <span class="badge">{filterLabel(row)}</span>
              <span class="text">
                <span class="mono">{t.sequence.frames(row.count, formatSeconds(row.exposure, locale))}</span>
                <span class="muted small">{formatDuration(rowSeconds(row))}</span>
              </span>
            </button>
            <button type="button" class="nudge" aria-label={t.sequence.fewer(filterLabel(row))} disabled={row.count <= 1} onclick={() => changeCount(i, -1)}>
              <Icon name="minus" />
            </button>
            <button type="button" class="nudge" aria-label={t.sequence.more(filterLabel(row))} onclick={() => changeCount(i, 1)}>
              <Icon name="plus" />
            </button>
          </li>
        {/each}
      </ul>
    </section>

    <section aria-labelledby="during">
      <h2 id="during">{t.sequence.during}</h2>
      <ul class="options">
        <li>
          <button type="button" class="option" onclick={() => (sheet = "focus")}>
            <span class="text">
              <span class="name">{t.sequence.autofocus}</span>
              <span class="muted small">{focusSummary(draft, t, locale)}</span>
            </span>
            <Icon name="chevronRight" />
          </button>
        </li>
        <li>
          <Toggle
            label={t.sequence.guiding}
            hint={canGuide || draft.guide ? t.sequence.guidingHint : t.sequence.noGuiding}
            checked={draft.guide ?? false}
            disabled={!canGuide && !draft.guide}
            onchange={(on) => (draft.guide = on)} />
        </li>
        {#if draft.rows.length > 1}
          <li>
            <Toggle
              label={t.sequence.rotate}
              hint={draft.order === "in_turn" ? t.sequence.rotateOff : t.sequence.rotateOn(draft.batch ?? 5)}
              checked={draft.order !== "in_turn"}
              onchange={(on) => (draft.order = on ? "batches" : "in_turn")} />
          </li>
        {/if}
        <li>
          <button type="button" class="option" onclick={() => (sheet = "night")}>
            <span class="text">
              <span class="name">{t.sequence.night}</span>
              <span class="muted small">{windowSummary(draft, t, locale)}</span>
            </span>
            <Icon name="chevronRight" />
          </button>
        </li>
        {#if camera?.can_cool || draft.cooling != null}
          <li>
            <button type="button" class="option" onclick={() => (sheet = "cooling")}>
              <span class="text">
                <span class="name">{t.sequence.cooling}</span>
                <span class="muted small">
                  {draft.cooling != null ? formatTemperature(draft.cooling, locale, 0) : t.sequence.off}
                </span>
              </span>
              <Icon name="chevronRight" />
            </button>
          </li>
        {/if}
        <li>
          <button type="button" class="option" onclick={() => (sheet = "end")}>
            <span class="text">
              <span class="name">{t.sequence.whenFinished}</span>
              <span class="muted small">{endSummary(draft, t, outputs)}</span>
            </span>
            <Icon name="chevronRight" />
          </button>
        </li>
      </ul>
    </section>

    {#if estimate}
      <section class="estimates">
        <div class="card estimate">
          <span class="muted small">
            {t.sequence.imagingTime}{estimate.ends ? ` · ${t.sequence.endsAt(formatTime(estimate.ends, locale))}` : ""}
          </span>
          <span class="mono">{formatDuration(estimate.duration)}</span>
          {#if estimate.starts}<span class="muted small">{t.sequence.startsAt(formatTime(estimate.starts, locale))}</span>{/if}
        </div>
        <div class="card estimate">
          <span class="muted small">
            {destination ? t.sequence.framesOn(estimate.frames, destination.label) : t.sequence.framesTotal(estimate.frames)}
          </span>
          {#if estimate.bytes !== null}
            <span class="mono">
              {destination
                ? t.sequence.ofFree(formatBytes(estimate.bytes, locale), formatBytes(destination.free, locale))
                : formatBytes(estimate.bytes, locale)}
            </span>
          {:else}
            <span class="muted small">{t.sequence.unknownSize}</span>
          {/if}
        </div>
      </section>
      {#if estimate.window === null}
        <p class="muted small">{t.sequence.noSite}</p>
      {:else if estimate.window === 0}
        <Banner icon="alert" tone="warning">{t.sequence.noWindow}</Banner>
      {:else if !fits}
        <Banner icon="alert" tone="warning">{t.sequence.tooLong(formatDuration(estimate.window))}</Banner>
      {/if}
    {/if}
    {#if problem}<Banner icon="alert" tone="error">{problem}</Banner>{/if}
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

    <div class="actions">
      <Button disabled={!builder.dirty || !!problem} busy={busy === "save"} onclick={() => void run("save")}>
        {builder.dirty ? t.sequence.save : t.sequence.saved}
      </Button>
      <Button variant="primary" wide disabled={!!running || !!problem || busy !== null} busy={busy === "start"} onclick={() => void run("start")}>
        {t.sequence.start}
      </Button>
    </div>

    <button type="button" class="disclosure" aria-expanded={advanced} onclick={() => (advanced = !advanced)}>
      <Icon name={advanced ? "chevronDown" : "chevronRight"} size={20} />
      {t.sequence.advanced}
    </button>
    {#if advanced}
      <section class="advanced">
        {#if draft.order !== "in_turn" && draft.rows.length > 1}
          <Stepper label={t.sequence.batch} bind:value={() => draft.batch ?? 5, (v) => v !== null && (draft.batch = v)} min={1} max={1000} />
        {/if}
        <h2>{t.sequence.steps}</h2>
        <p class="muted small">{t.sequence.stepsHint}</p>
        {#if steps}<SequenceSteps sequence={steps} {outputs} />{/if}
      </section>
    {/if}
  {/if}
</div>

{#if draft && editing !== null}
  {@const row = draft.rows[editing]}
  {#if row}
    <RowSheet
      {row}
      {filters}
      canRemove={draft.rows.length > 1}
      onremove={() => {
        if (editing !== null) draft.rows.splice(editing, 1);
        editing = null;
      }}
      onclose={() => (editing = null)} />
  {/if}
{/if}
{#if draft && sheet}
  <SequenceSheets kind={sheet} template={draft} {outputs} canCool={camera?.can_cool ?? false} onclose={() => (sheet = null)} />
{/if}

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-4);
    padding-bottom: var(--space-6);
  }
  h2 {
    margin: 0;
    font-size: 15px;
    line-height: 22px;
    font-weight: 600;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    text-align: left;
  }
  .name {
    font-weight: 500;
  }
  .target {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .target .name {
    font-weight: 600;
  }
  .heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .rows,
  .options {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li,
  .options li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 56px;
    border-bottom: 1px solid var(--line);
  }
  .row-main,
  .option {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    min-height: 56px;
    padding: var(--space-1) 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .option :global(svg) {
    color: var(--muted);
  }
  .badge {
    flex: none;
    min-width: 56px;
    height: 28px;
    padding: 0 var(--space-2);
    display: grid;
    place-items: center;
    border-radius: 8px;
    background: var(--raised);
    font-size: 13px;
    font-weight: 600;
  }
  .nudge {
    flex: none;
    width: var(--touch);
    height: var(--touch);
    display: grid;
    place-items: center;
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  .nudge:disabled {
    color: var(--muted);
    cursor: default;
  }
  .estimates {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .estimate {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
  }
  .disclosure {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--touch);
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .advanced {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
