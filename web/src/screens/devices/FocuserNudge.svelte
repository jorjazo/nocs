<script lang="ts">
  // In and out by the chosen step, or Stop while the focuser moves: what
  // focusing by hand needs while a loop runs, in Live view and in the
  // focuser's sheet.
  import Icon from "../../components/Icon.svelte";
  import { abortFocuser, moveFocuser } from "../../lib/api";
  import { capture } from "../../lib/camera.svelte";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { FocuserState } from "../../lib/types";

  let {
    focuser,
    disabled = false,
    run,
  }: {
    focuser: FocuserState;
    disabled?: boolean;
    // Runs an action and reports its failure where the screen shows errors.
    run: (action: () => Promise<unknown>) => Promise<void>;
  } = $props();

  const t = $derived(i18n.t);
  const step = $derived(formatPlain(capture.focusStep, i18n.locale));
  const max = $derived(focuser.max_position);
</script>

<div class="nudge">
  {#if focuser.moving}
    <button
      type="button"
      class="button stop"
      disabled={disabled || !focuser.can_abort}
      onclick={() => void run(abortFocuser)}>
      {t.focuser.stop}
    </button>
  {:else}
    <button
      type="button"
      class="button"
      aria-label={t.focuser.inward(step)}
      disabled={disabled || focuser.position - capture.focusStep < 0}
      onclick={() => void run(() => moveFocuser({ steps: -capture.focusStep }))}>
      <Icon name="minus" size={20} /><span class="mono">{step}</span>
    </button>
    <button
      type="button"
      class="button"
      aria-label={t.focuser.outward(step)}
      disabled={disabled || (max !== null && focuser.position + capture.focusStep > max)}
      onclick={() => void run(() => moveFocuser({ steps: capture.focusStep }))}>
      <Icon name="plus" size={20} /><span class="mono">{step}</span>
    </button>
  {/if}
</div>

<style>
  .nudge {
    display: flex;
    gap: var(--space-2);
  }
  .button {
    display: inline-flex;
    flex: 1 1 0;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-width: 88px;
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-button);
    background: var(--raised);
    color: var(--text);
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
  }
  .button:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .stop {
    border-color: var(--error);
    color: var(--error);
  }
</style>
