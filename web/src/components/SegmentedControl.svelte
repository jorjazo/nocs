<script lang="ts" generics="T extends string">
  let {
    label,
    options,
    value,
    onchange,
  }: {
    // Accessible name of the group.
    label: string;
    options: readonly { value: T; label: string }[];
    value: T;
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
      onclick={() => onchange(option.value)}>
      {option.label}
    </button>
  {/each}
</div>

<style>
  .segmented {
    display: flex;
    gap: var(--space-1);
    padding: var(--space-1);
    border-radius: var(--radius-button);
    background: var(--raised);
  }
  button {
    flex: 1 1 0;
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
  .selected {
    background: var(--accent);
    color: var(--on-accent);
    font-weight: 600;
  }
</style>
