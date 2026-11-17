<script lang="ts" generics="T extends string">
  // A small choice of two or three options, for bars over an image where a full
  // segmented control would not fit (Explore's camera and histogram scale).
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

<div class="pills" role="radiogroup" aria-label={label}>
  {#each options as option (option.value)}
    <button
      type="button"
      role="radio"
      aria-checked={option.value === value}
      class:selected={option.value === value}
      {disabled}
      onclick={() => onchange(option.value)}>{option.label}</button>
  {/each}
</div>

<style>
  .pills {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--surface) 88%, transparent);
    border: 1px solid var(--line);
  }
  button {
    min-height: var(--touch);
    padding: 0 12px;
    border: 0;
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--muted);
    font-size: 13px;
    white-space: nowrap;
    cursor: pointer;
  }
  button.selected {
    background: color-mix(in srgb, var(--accent) var(--tint), var(--raised));
    color: var(--accent);
    font-weight: 600;
  }
  button:disabled {
    cursor: default;
    opacity: 0.55;
  }
</style>
