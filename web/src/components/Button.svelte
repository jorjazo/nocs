<script lang="ts">
  import type { Snippet } from "svelte";

  // One primary (accent) button per screen (docs/ux.md §5).
  type Variant = "primary" | "secondary" | "text" | "danger";

  let {
    variant = "secondary",
    type = "button",
    disabled = false,
    busy = false,
    wide = false,
    label,
    onclick,
    children,
  }: {
    variant?: Variant;
    type?: "button" | "submit";
    disabled?: boolean;
    // Waiting for the server: shows a spinner and refuses more presses.
    busy?: boolean;
    wide?: boolean;
    // Accessible name when the visible content is not enough.
    label?: string;
    onclick?: (event: MouseEvent) => void;
    children: Snippet;
  } = $props();
</script>

<button
  class="button {variant}"
  class:wide
  {type}
  disabled={disabled || busy}
  aria-busy={busy}
  aria-label={label}
  {onclick}>
  {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}
  {@render children()}
</button>

<style>
  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--touch);
    min-width: var(--touch);
    padding: 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid transparent;
    font-size: 15px;
    line-height: 20px;
    font-weight: 600;
    text-align: center;
    cursor: pointer;
    transition: filter 120ms;
  }
  .button:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .button:active:not(:disabled) {
    filter: brightness(1.15);
  }
  .wide {
    width: 100%;
  }
  .primary {
    min-height: var(--primary-height);
    background: var(--accent);
    color: var(--on-accent);
    font-size: 17px;
  }
  .secondary {
    background: var(--raised);
    border-color: var(--line);
    color: var(--text);
  }
  .text {
    background: transparent;
    color: var(--accent);
    padding: 0 var(--space-2);
  }
  .danger {
    background: color-mix(in srgb, var(--error) var(--tint), var(--surface));
    border-color: color-mix(in srgb, var(--error) 55%, transparent);
    color: var(--error);
  }
  .spinner {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid currentColor;
    border-right-color: transparent;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(1turn);
    }
  }
</style>
