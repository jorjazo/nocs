<script lang="ts">
  // Live stacking in Live view (ADR 0039): the switch, what the stack holds and
  // how its frames are calibrated, the latest frame's outcome, a new stack and
  // its look. Which image the viewer shows is chosen here, per device.
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { resetStack, setStacking } from "../../lib/api";
  import { formatDecimal, formatDuration } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { calibrated, folded, outcome, parts, type Part } from "../../lib/stack";
  import { stackView, type StackView } from "../../lib/stackview.svelte";
  import type { StackState } from "../../lib/types";
  import LookSheet from "./LookSheet.svelte";

  let {
    stack,
    owner,
    run,
  }: {
    stack: StackState;
    owner: boolean;
    // The screen's own action wrapper: reports failures in its dock.
    run: (action: () => Promise<unknown>) => Promise<void>;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const current = $derived(stack.on ? stack.current : null);
  const last = $derived(current?.last ? outcome(current.last) : null);
  let looking = $state(false);

  function part(p: Part): string {
    return "count" in p ? t.stack.parts[p.kind](p.count) : t.stack.parts[p.kind];
  }

  const counts = $derived.by(() => {
    if (!current) return "";
    const parts = [t.stack.frames(current.frames)];
    if (current.exposure > 0) parts.push(t.stack.total(formatDuration(current.exposure)));
    if (current.rejected > 0) parts.push(t.stack.leftOut(current.rejected));
    if (current.skipped > 0) parts.push(t.stack.skipped(current.skipped));
    return parts.join(" · ");
  });
</script>

<section class="stack" aria-labelledby="stack-title">
  <h2 class="visually-hidden" id="stack-title">{t.stack.title}</h2>
  <Toggle
    label={t.stack.toggle}
    hint={stack.on ? undefined : t.stack.toggleHint}
    checked={stack.on}
    disabled={!owner}
    onchange={(on) => void run(() => setStacking(on))} />

  {#if stack.on}
    {#if current?.preview}
      <SegmentedControl
        label={t.stack.show}
        options={[
          { value: "stack" as StackView, label: t.stack.stack },
          { value: "frame" as StackView, label: t.stack.frame },
        ]}
        value={stackView.view}
        onchange={(view) => stackView.set(view)} />
    {/if}

    {#if stack.status === "preparing"}
      <p class="caption muted" role="status">{stack.message ?? t.stack.preparing}</p>
    {:else if stack.status === "failed"}
      <p class="caption error" role="status">{t.stack.failed}{stack.error ? `: ${stack.error}` : ""}</p>
    {:else if !current}
      <p class="caption muted">{t.stack.waiting}</p>
    {/if}

    {#if current}
      <div class="summary">
        <span>{counts}</span>
        <Chip tone={calibrated(current) === "none" ? "neutral" : "ok"}>{t.stack.calibration[calibrated(current)]}</Chip>
      </div>
      {#if last}
        <p class="caption" class:muted={last.kind === "accepted"} class:warning={last.kind === "left"} role="status">
          {#if last.kind === "accepted"}
            {t.stack.moved(formatDecimal(last.shift, locale, 1), formatDecimal(folded(last.rotation), locale, 1))}
          {:else}
            {last.cause ? t.stack.left[last.cause] : last.reason}
          {/if}
        </p>
      {/if}
      <p class="caption muted notes">{t.stack.notes}: {parts(current).map(part).join(" · ")}</p>
    {/if}

    <div class="buttons">
      <Button disabled={!owner || !current} onclick={() => void run(resetStack)}>{t.stack.newStack}</Button>
      <Button variant="text" disabled={!owner} onclick={() => (looking = true)}>{t.stack.look}</Button>
    </div>
  {/if}
</section>

{#if looking}
  <LookSheet look={stack.look} {run} onclose={() => (looking = false)} />
{/if}

<style>
  .stack {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2) 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
  .summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .notes {
    overflow-wrap: anywhere;
  }
  .warning {
    color: var(--warning);
  }
  .error {
    color: var(--error);
  }
</style>
