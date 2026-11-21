<script lang="ts">
  // The plan over the Plan view's image, where Explore has its go to: how the run
  // stands, the target it takes with its lines, the targets in priority with how far
  // each is, the frame in progress, the latest events, and the way to the targets.
  // Folded, its icon keeps a dot in the run's tone.
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import { plannedName } from "../../lib/catalog.svelte";
  import { formatDuration, formatSeconds, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { lineLeft, targetCount, targetDone, targetSeconds } from "../../lib/plan";
  import { href } from "../../lib/router.svelte";
  import { isActive } from "../../lib/sequence";
  import { describeEvent, describeStep, groupName } from "../../lib/sequence.svelte";
  import type { NightPlan, PowerOutput, SequenceEvent, SequenceRun } from "../../lib/types";
  import ToolCard from "../explore/ToolCard.svelte";

  let {
    run,
    plan,
    events,
    exposing,
    outputs,
    open,
    ontoggle,
  }: {
    // The plan's run, in progress or the last one; null without one.
    run: SequenceRun | null;
    plan: NightPlan | null;
    events: SequenceEvent[];
    // The frame in progress: its line's name and number, and the seconds left of it.
    exposing: { label: string; frame: number; count: number; remaining: number | null; total: number } | null;
    outputs: PowerOutput[];
    open: boolean;
    ontoggle: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);
  const active = $derived(isActive(run));

  type Shown = keyof typeof t.session.states;
  const shown = $derived<Shown | null>(run ? (run.state === "finished" ? (run.outcome ?? "completed") : run.state) : null);
  const chip = $derived.by((): { tone: Tone; text: string } => {
    if (!shown) return { tone: "neutral", text: t.sequence.state.idle };
    const tone: Tone =
      shown === "failed" ? "error" : shown === "paused" || shown === "pausing" || shown === "stopped" ? "warning" : shown === "completed" ? "ok" : "accent";
    return { tone, text: t.session.states[shown] };
  });

  const targets = $derived(plan?.targets ?? []);
  const taking = $derived(active && run?.target ? (targets.find((target) => target.id === run.target) ?? null) : null);
  // The line in progress: lines are taken in order, each to its end.
  const line = $derived(taking ? ((taking.lines ?? []).find((l) => lineLeft(l) > 0) ?? null) : null);
  const left = $derived(targets.reduce((sum, target) => sum + targetSeconds(target), 0));
  const recent = $derived([...events].reverse().slice(0, 3));
</script>

<ToolCard icon="plan" title={p.widget} {open} {ontoggle} side="right" wide tone={chip.tone === "neutral" ? null : chip.tone} toneText={chip.text}>
  {#snippet status()}<Chip tone={chip.tone}>{chip.text}</Chip>{/snippet}
  <div class="body">
    {#if taking}
      <p class="name">{plannedName(taking, locale)}</p>
      <ol class="rows">
        {#each taking.lines ?? [] as each (each.id)}
          <li class:current={each.id === line?.id}>
            <span class="badge">{groupName({ frame_type: "light", filter: each.filter, count: each.count }, t)}</span>
            <span class="mono small frames">{t.sequence.groupProgress(Math.min(each.done ?? 0, each.count), each.count)}</span>
            <span class="bar"><span style:width="{(100 * Math.min(each.done ?? 0, each.count)) / each.count}%"></span></span>
          </li>
        {/each}
      </ol>
    {:else if active && run?.step?.kind === "schedule"}
      <p class="muted small">{p.noTarget}</p>
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
    {#if targets.length}
      <ol class="targets" aria-label={p.targets}>
        {#each targets as target, i (target.id)}
          {@const count = targetCount(target)}
          <li class:current={target.id === taking?.id}>
            <span class="rank mono muted">{i + 1}</span>
            <a class="target" href={href({ screen: "plan-target", id: target.id })}>{plannedName(target, locale)}</a>
            <span class="mono small">{count ? t.sequence.groupProgress(targetDone(target), count) : p.noLines}</span>
          </li>
        {/each}
      </ol>
      {#if left > 0}<p class="muted small">{p.framesLeft(formatDuration(left))}</p>{/if}
    {:else}
      <p class="muted small">{p.empty}</p>
    {/if}
    {#if run?.error}<p class="error small">{run.error}</p>{/if}
    {#if recent.length && run}
      <ol class="events" aria-label={t.sequence.events}>
        {#each recent as event, i (event.time + event.kind + i)}
          <li class="small"><span class="mono muted">{formatTime(event.time, locale)}</span> {describeEvent(event, t, locale)}</li>
        {/each}
      </ol>
    {/if}
    <a class="link" href={href({ screen: "plan-edit" })}>{p.configure}</a>
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
  .targets,
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
    background: var(--line);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .targets li {
    display: grid;
    grid-template-columns: 1.5em minmax(0, 1fr) auto;
    align-items: baseline;
    gap: var(--space-2);
  }
  .target {
    color: var(--text);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .targets .current .target {
    color: var(--accent);
    font-weight: 600;
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
