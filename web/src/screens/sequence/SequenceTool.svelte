<script lang="ts">
  // The sequence over the Sequences view's image, where Explore has its go to: how the
  // run stands (or what the sequence would take), each group with its frames, the
  // frame in progress, what was framed, the latest events, and the way to configure
  // the sequence. Folded, its icon keeps a dot in the run's tone.
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import { formatDuration, formatSeconds, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { href } from "../../lib/router.svelte";
  import { currentPlan, groupExposure, isActive, runProgress } from "../../lib/sequence";
  import { describeEvent, describeStep, groupFrames, groupName } from "../../lib/sequence.svelte";
  import type { PowerOutput, SequenceEvent, SequenceRun, Template } from "../../lib/types";
  import ToolCard from "../explore/ToolCard.svelte";

  let {
    run,
    template,
    events,
    exposing,
    outputs,
    open,
    ontoggle,
  }: {
    // The run of this sequence, in progress or the last one; null without one.
    run: SequenceRun | null;
    template: Template | null;
    events: SequenceEvent[];
    // The frame in progress: its row's name and number, and the seconds left of it.
    exposing: { label: string; frame: number; count: number; remaining: number | null; total: number } | null;
    outputs: PowerOutput[];
    open: boolean;
    ontoggle: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const locale = $derived(i18n.locale);
  const active = $derived(isActive(run));

  type Shown = keyof typeof t.session.states;
  const shown = $derived<Shown | null>(run ? (run.state === "finished" ? (run.outcome ?? "completed") : run.state) : null);
  const chip = $derived.by((): { tone: Tone; text: string } => {
    if (run?.prompt && active) return { tone: "warning", text: s.state.waiting };
    if (!shown) return { tone: "neutral", text: s.state.idle };
    const tone: Tone =
      shown === "failed" ? "error" : shown === "paused" || shown === "pausing" || shown === "stopped" ? "warning" : shown === "completed" ? "ok" : "accent";
    return { tone, text: t.session.states[shown] };
  });

  // The groups: the run's, with their frames done, or the sequence's as planned.
  type Row = { name: string; frames: string; done: number; count: number; current: boolean };
  const progress = $derived(run ? runProgress(run) : null);
  const here = $derived(run && active ? currentPlan(run) : null);
  const rows = $derived.by((): Row[] => {
    if (run && progress) {
      return progress.rows.map((r) => {
        const group = { frame_type: r.frameType, filter: r.filter, exposure: r.exposure, count: r.count };
        return { name: groupName(group, t), frames: groupFrames(group, t, locale), done: r.done, count: r.count, current: r.path === here && r.done < r.count };
      });
    }
    return (template?.groups ?? []).map((g) => ({ name: groupName(g, t), frames: groupFrames(g, t, locale), done: 0, count: g.count, current: false }));
  });
  const planned = $derived((template?.groups ?? []).reduce((sum, g) => sum + g.count * (groupExposure(g) + 3), 0));
  const left = $derived(run && active && progress ? progress.left : run ? null : planned);
  const ends = $derived(run && active && progress && progress.left > 0 ? new Date(Date.now() + progress.left * 1000).toISOString() : null);
  const framed = $derived(run ? (Object.values(run.plans).find((p) => p.target)?.target ?? null) : null);
  const recent = $derived([...events].reverse().slice(0, 3));
</script>

<ToolCard icon="sequence" title={s.widget} {open} {ontoggle} side="right" wide tone={chip.tone === "neutral" ? null : chip.tone} toneText={chip.text}>
  {#snippet status()}<Chip tone={chip.tone}>{chip.text}</Chip>{/snippet}
  <div class="body">
    {#if template || run}
      <p class="name">{run?.name ?? template?.name}</p>
    {/if}
    {#if framed}<p class="muted small">{s.framed(framed)}</p>{/if}
    {#if rows.length}
      <ol class="rows">
        {#each rows as row, i (i)}
          <li class:current={row.current}>
            <span class="badge">{row.name}</span>
            <span class="mono small frames">{run ? s.groupProgress(Math.min(row.done, row.count), row.count) : row.frames}</span>
            <span class="bar"><span style:width="{(100 * Math.min(row.done, row.count)) / row.count}%"></span></span>
          </li>
        {/each}
      </ol>
    {/if}
    {#if active && run}
      {#if exposing}
        <p class="small">
          {t.session.exposing(exposing.label, exposing.frame, exposing.count)}
          {#if exposing.remaining !== null}<span class="mono"> · {formatSeconds(Math.max(0, Math.ceil(exposing.remaining)), locale)}</span>{/if}
        </p>
      {:else}
        <p class="small">{describeStep(run, t, locale, outputs)}</p>
      {/if}
    {/if}
    {#if left !== null && left > 0}
      <p class="muted small">
        {#if active}
          {s.timeLeft(formatDuration(left))}{ends ? ` · ${t.session.endsAt(formatTime(ends, locale))}` : ""}
        {:else}
          {s.imagingTime}: {formatDuration(left)}
        {/if}
      </p>
    {/if}
    {#if run?.error}<p class="error small">{run.error}</p>{/if}
    {#if recent.length && run}
      <ol class="events" aria-label={s.events}>
        {#each recent as event, i (event.time + event.kind + i)}
          <li class="small"><span class="mono muted">{formatTime(event.time, locale)}</span> {describeEvent(event, t, locale)}</li>
        {/each}
      </ol>
    {/if}
    <a class="link" href={href({ screen: "sequence-edit" })}>{s.configureTitle}</a>
  </div>
</ToolCard>

<style>
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .name {
    font-weight: 600;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  .error {
    color: var(--error);
  }
  .rows,
  .events {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .rows li {
    display: grid;
    grid-template-columns: auto auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-2);
  }
  .badge {
    min-width: 44px;
    padding: 0 var(--space-2);
    border-radius: 8px;
    background: var(--raised);
    font-size: 13px;
    font-weight: 600;
    text-align: center;
  }
  .current .badge {
    background: color-mix(in srgb, var(--accent) var(--tint), var(--raised));
    color: var(--accent);
  }
  .bar {
    height: 4px;
    border-radius: 2px;
    background: var(--line);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .events li {
    overflow-wrap: anywhere;
  }
  .link {
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
</style>
