<script lang="ts" generics="T extends string">
  let {
    label,
    options,
    value,
    disabled = false,
    onchange,
  }: {
    // Accessible name of the group.
    label: string;
    options: readonly { value: T; label: string }[];
    value: T;
    disabled?: boolean;
    onchange: (value: T) => void;
  } = $props();
</script>

<div class="segmented" role="radiogroup" aria-label={label}>
  {#each options as option (option.value)}
    <button
      type="button"
      role="radio"
      aria-checked={option.value === value}
      class:selected={option.value === value}
      {disabled}
      onclick={() => onchange(option.value)}>
      {option.label}
    </button>
  {/each}
</div>

<style>
  /* Many options (a filter wheel's slots) scroll sideways rather than shrink
     below the touch size. */
  .segmented {
    display: flex;
    gap: var(--space-1);
    padding: var(--space-1);
    border-radius: var(--radius-button);
    background: var(--raised);
    overflow-x: auto;
    scrollbar-width: none;
  }
  button {
    flex: 1 0 auto;
    min-width: var(--touch);
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 0;
    border-radius: var(--radius-tile);
    background: transparent;
    color: var(--muted);
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
  }
  button:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .selected {
    background: var(--accent);
    color: var(--on-accent);
    font-weight: 600;
  }
</style>
