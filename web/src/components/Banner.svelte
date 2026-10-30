<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import type { IconName } from "./icons";

  let {
    icon,
    tone = "neutral",
    children,
    action,
  }: { icon: IconName; tone?: "neutral" | "warning" | "error"; children: Snippet; action?: Snippet } = $props();
</script>

<div class="banner {tone}" role="status">
  <Icon name={icon} size={20} />
  <span class="text">{@render children()}</span>
  {#if action}{@render action()}{/if}
</div>

<style>
  .banner {
    --tone: var(--muted);
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: var(--touch);
    padding: var(--space-1) var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid color-mix(in srgb, var(--tone) 40%, transparent);
    background: color-mix(in srgb, var(--tone) var(--tint), var(--surface));
    color: var(--tone);
  }
  .warning {
    --tone: var(--warning);
  }
  .error {
    --tone: var(--error);
  }
  .text {
    flex: 1;
    min-width: 0;
    color: var(--text);
  }
</style>
