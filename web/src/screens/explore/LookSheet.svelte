<script lang="ts">
  // How the live stack is stretched into a picture (ADR 0040). The server keeps
  // the look for every client and shows the current stack with it at once, so
  // each change is sent as it is chosen. The sheet keeps its own copy: the
  // server's comes back only after the stack is drawn again, and a second tap
  // before that must not undo the first.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { untrack } from "svelte";
  import { setStackLook } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";
  import { BACKGROUNDS, complete, DEFAULT_LOOK, type Look, nearest, SATURATIONS, SHADOWS } from "../../lib/stack";
  import type { StackLook } from "../../lib/types";

  let { look: given, onclose }: { look: StackLook; onclose: () => void } = $props();

  const t = $derived(i18n.t);
  let look = $state<Look>(untrack(() => complete(given)));
  let error = $state("");

  async function send(next: Look): Promise<void> {
    look = next;
    error = "";
    try {
      await setStackLook(next);
    } catch (e) {
      error = errorText(e, t);
    }
  }

  function change(update: Partial<StackLook>): void {
    void send({ ...look, ...update });
  }

  function options(steps: readonly number[], labels: string[]): { value: string; label: string }[] {
    return steps.map((step, i) => ({ value: String(step), label: labels[i] ?? String(step) }));
  }
</script>

<Sheet title={t.stack.lookTitle} {onclose}>
  <div class="look">
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
    <div class="group">
      <span class="label muted">{t.stack.background}</span>
      <SegmentedControl
        label={t.stack.background}
        options={options(BACKGROUNDS, t.stack.backgrounds)}
        value={String(nearest(BACKGROUNDS, look.background))}
        onchange={(value) => change({ background: Number(value) })} />
    </div>
    <div class="group">
      <span class="label muted">{t.stack.blackPoint}</span>
      <SegmentedControl
        label={t.stack.blackPoint}
        options={options(SHADOWS, t.stack.blackPoints)}
        value={String(nearest(SHADOWS, look.shadows))}
        onchange={(value) => change({ shadows: Number(value) })} />
    </div>
    <div class="group">
      <span class="label muted">{t.stack.saturation}</span>
      <SegmentedControl
        label={t.stack.saturation}
        options={options(SATURATIONS, t.stack.saturations)}
        value={String(nearest(SATURATIONS, look.saturation))}
        onchange={(value) => change({ saturation: Number(value) })} />
    </div>
    <Toggle
      label={t.stack.linked}
      hint={t.stack.linkedHint}
      checked={look.linked}
      onchange={(linked) => change({ linked })} />
  </div>
  {#snippet actions()}
    <Button variant="text" onclick={() => void send(DEFAULT_LOOK)}>{t.stack.defaults}</Button>
  {/snippet}
</Sheet>

<style>
  .look {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
</style>
