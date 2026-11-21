<script lang="ts">
  // The plan's targets (#/plan/edit), in priority: the run takes the first that is up
  // with frames left. Each says its lines, how far it is over every night, what is
  // left, and how it does tonight; up and down change its place, a tap opens its page,
  // and Add target finds another. Changes are saved a moment after they are made, and
  // while the plan runs they count from its next look.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import { getVisibility } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { plannedName } from "../../lib/catalog.svelte";
  import { formatDuration } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { isPlanRun, moved, targetCount, targetDone, targetIntegration, targetSeconds } from "../../lib/plan";
  import { plan } from "../../lib/plan.svelte";
  import { href, router } from "../../lib/router.svelte";
  import { isActive } from "../../lib/sequence";
  import { groupName } from "../../lib/sequence.svelte";
  import type { PlanTarget, TargetVisibility } from "../../lib/types";

  const t = $derived(i18n.t);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);

  $effect(() => plan.sync(live.app.plan ?? null));
  $effect(() => {
    if (!plan.draft) return;
    void JSON.stringify(plan.draft);
    plan.changed();
  });

  const targets = $derived(plan.draft?.targets ?? []);
  const run = $derived(live.app.sequence?.run ?? null);
  const taking = $derived(isPlanRun(run) && isActive(run) ? (run?.target ?? null) : null);
  const minimum = $derived(plan.draft?.actions?.min_altitude ?? 30);

  // How each does tonight, asked again when the targets or the minimum change.
  let seen = $state<Record<string, TargetVisibility>>({});
  const where = $derived(targets.map((target) => `${target.ra.toFixed(4)},${target.dec.toFixed(4)}`).join(";"));
  $effect(() => {
    const keys = where;
    const min = minimum;
    const ids = targets.map((target) => target.id);
    if (!keys) {
      seen = {};
      return;
    }
    const timer = setTimeout(() => {
      getVisibility(keys.split(";"), min)
        .then((v) => {
          if (keys === where) seen = Object.fromEntries(v.targets.flatMap((target, i) => (ids[i] ? [[ids[i], target]] : [])));
        })
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  });

  function move(index: number, by: number): void {
    if (!plan.draft) return;
    plan.draft.targets = moved(targets, index, by);
  }

  function tonight(target: PlanTarget): { tone: "ok" | "neutral"; text: string } | null {
    const v = seen[target.id];
    if (!v) return null;
    if (v.observable > 0) return { tone: "ok", text: t.plan.upFor(formatDuration(v.observable)) };
    return { tone: "neutral", text: v.above_horizon > 0 ? t.plan.lowTonight : t.plan.notUp };
  }

  function lines(target: PlanTarget): string {
    return (target.lines ?? []).map((line) => groupName({ frame_type: "light", filter: line.filter, count: line.count }, t)).join(" · ");
  }
</script>

<div class="page">
  <a class="back" href={href({ screen: "plan" })}><Icon name="chevronLeft" />{t.tabs.plan}</a>
  <header class="title">
    <h1>{p.targetsTitle}</h1>
    <p class="muted">{p.targetsHint}</p>
  </header>

  {#if plan.error}<Banner icon="alert" tone="error">{plan.error}</Banner>{/if}

  {#if !plan.draft}
    <p class="muted" role="status">{t.sequence.loading}</p>
  {:else if !targets.length}
    <EmptyState icon="plan" title={p.empty} body={p.emptyBody}>
      {#snippet action()}
        {#if owner}<Button variant="primary" onclick={() => router.go({ screen: "plan-add" })}>{p.addTarget}</Button>{/if}
      {/snippet}
    </EmptyState>
  {:else}
    <ol class="targets">
      {#each targets as target, i (target.id)}
        {@const count = targetCount(target)}
        {@const done = targetDone(target)}
        {@const up = tonight(target)}
        {@const left = targetSeconds(target)}
        <li class:current={target.id === taking}>
          <span class="rank mono">{i + 1}</span>
          <a class="target" href={href({ screen: "plan-target", id: target.id })}>
            <span class="name">{plannedName(target, locale)}</span>
            <span class="muted small">{count ? lines(target) : p.noLines}</span>
            {#if count}
              <span class="bar"><span style:width="{(100 * done) / count}%"></span></span>
              <span class="muted small mono">
                {t.sequence.groupProgress(done, count)}
                {#if targetIntegration(target) > 0}· {formatDuration(targetIntegration(target))}{/if}
                {#if left > 0}· {p.left(formatDuration(left))}{:else}· {p.done}{/if}
              </span>
            {/if}
            <span class="chips">
              {#if target.id === taking}<Chip tone="accent">{p.taking}</Chip>{/if}
              {#if up}<Chip tone={up.tone}>{up.text}</Chip>{/if}
            </span>
          </a>
          {#if owner}
            <span class="order">
              <Button variant="text" disabled={i === 0} label={p.up} onclick={() => move(i, -1)}><Icon name="up" size={20} /></Button>
              <Button variant="text" disabled={i === targets.length - 1} label={p.down} onclick={() => move(i, 1)}><Icon name="down" size={20} /></Button>
            </span>
          {/if}
        </li>
      {/each}
    </ol>
    {#if owner}
      <Button variant="primary" onclick={() => router.go({ screen: "plan-add" })}><Icon name="plus" size={20} />{p.addTarget}</Button>
    {/if}
  {/if}
  {#if plan.saving}<p class="caption muted">{t.sequence.savingDraft}</p>{/if}
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
  p {
    margin: 0;
  }
  .small,
  .caption {
    font-size: 13px;
    line-height: 18px;
  }
  .targets {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--line);
  }
  .targets li {
    display: grid;
    grid-template-columns: 2em minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--line);
  }
  .rank {
    color: var(--muted);
    text-align: center;
  }
  .current .rank {
    color: var(--accent);
  }
  .target {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    color: var(--text);
    text-decoration: none;
  }
  .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .bar {
    height: 4px;
    margin: var(--space-1) 0;
    background: var(--line);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin-top: var(--space-1);
  }
  .chips:empty {
    display: none;
  }
  .order {
    display: flex;
    flex-direction: column;
  }
</style>
