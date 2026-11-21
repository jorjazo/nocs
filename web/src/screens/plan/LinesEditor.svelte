<script lang="ts">
  // A target's lines of lights, in the order they are taken: each with its filter,
  // exposure and count, and the frames it has (the server's); a sheet to edit one,
  // and a new one after the last.
  import Button from "../../components/Button.svelte";
  import Icon from "../../components/Icon.svelte";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { newId, newLine, planIds } from "../../lib/plan";
  import { plan } from "../../lib/plan.svelte";
  import { groupName } from "../../lib/sequence.svelte";
  import type { PlanTarget } from "../../lib/types";
  import LineSheet from "./LineSheet.svelte";

  let { target, disabled = false }: { target: PlanTarget; disabled?: boolean } = $props();

  const t = $derived(i18n.t);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const filters = $derived((live.app.filter_wheel?.names ?? []).filter((name) => name));
  let editing = $state<number | null>(null);

  function add(): void {
    const lines = target.lines ?? [];
    const taken = [...(plan.draft ? planIds(plan.draft) : []), target.id, ...lines.map((l) => l.id)];
    const camera_ = { gain: camera?.gain ?? null, offset: camera?.offset ?? null };
    target.lines = [...lines, newLine(lines, filters, newId(taken), camera_)];
    editing = target.lines.length - 1;
  }

  function remove(index: number): void {
    target.lines = (target.lines ?? []).filter((_, i) => i !== index);
    editing = null;
  }

  const line = $derived(editing !== null ? (target.lines ?? [])[editing] : undefined);
</script>

<div class="lines">
  {#if (target.lines ?? []).length}
    <ol>
      {#each target.lines ?? [] as each, i (each.id)}
        {@const done = Math.min(each.done ?? 0, each.count)}
        <li>
          <button type="button" class="line" {disabled} onclick={() => (editing = i)}>
            <span class="badge">{groupName({ frame_type: "light", filter: each.filter, count: each.count }, t)}</span>
            <span class="text">
              <span>{p.lineSummary(formatPlain(each.exposure, locale), each.count)}</span>
              <span class="bar"><span style:width="{(100 * done) / each.count}%"></span></span>
            </span>
            <span class="mono small muted">{t.sequence.groupProgress(done, each.count)}</span>
            <Icon name="chevronRight" />
          </button>
        </li>
      {/each}
    </ol>
  {:else}
    <p class="muted small">{p.noLinesHint}</p>
  {/if}
  <Button variant="text" {disabled} onclick={add}><Icon name="plus" size={20} />{p.addLine}</Button>
</div>

{#if line}
  <LineSheet {line} {filters} onremove={() => editing !== null && remove(editing)} onclose={() => (editing = null)} />
{/if}

<style>
  .lines {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    align-items: stretch;
  }
  .lines > :global(button) {
    align-self: flex-start;
  }
  ol {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--line);
  }
  li {
    border-bottom: 1px solid var(--line);
  }
  .line {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    min-height: 56px;
    padding: var(--space-1) 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .line:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .line :global(svg) {
    color: var(--muted);
  }
  .badge {
    min-width: 44px;
    padding: 0 var(--space-2);
    background: var(--raised);
    font-size: 13px;
    font-weight: 600;
    text-align: center;
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
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
  .small {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
  }
</style>
