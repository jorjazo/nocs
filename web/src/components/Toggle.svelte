<script lang="ts">
  // The whole row is the switch, so the touch target is the row, not the knob.
  let {
    label,
    hint,
    checked,
    disabled = false,
    onchange,
  }: {
    label: string;
    hint?: string;
    checked: boolean;
    disabled?: boolean;
    onchange: (checked: boolean) => void;
  } = $props();
</script>

<button type="button" class="toggle" role="switch" aria-checked={checked} {disabled} onclick={() => onchange(!checked)}>
  <span class="text">
    <span class="name">{label}</span>
    {#if hint}<span class="hint">{hint}</span>{/if}
  </span>
  <span class="track" class:on={checked} aria-hidden="true"><span class="knob"></span></span>
</button>

<style>
  .toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    width: 100%;
    min-height: var(--touch);
    padding: var(--space-2) 0;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }
  .toggle:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .hint {
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
  }
  .track {
    flex: none;
    position: relative;
    width: 56px;
    height: 32px;
    border-radius: var(--radius-full);
    background: var(--raised);
    border: 1px solid var(--line);
    transition: background 150ms;
  }
  .knob {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--muted);
    transition: transform 150ms;
  }
  /* On: accent track and a dark knob on the right; off: hollow look. */
  .on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .on .knob {
    background: var(--on-accent);
    transform: translateX(24px);
  }
</style>
