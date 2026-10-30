<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import type { IconName } from "./icons";

  let {
    icon,
    title,
    subtitle,
    error,
    trailing,
  }: {
    icon: IconName;
    title: string;
    subtitle?: string;
    // Shown under the row, in words, when something is wrong.
    error?: string | null;
    trailing?: Snippet;
  } = $props();
</script>

<li class="row">
  <span class="tile"><Icon name={icon} /></span>
  <span class="text">
    <span class="title">{title}</span>
    {#if subtitle}<span class="subtitle">{subtitle}</span>{/if}
    {#if error}<span class="error">{error}</span>{/if}
  </span>
  {#if trailing}<span class="trailing">{@render trailing()}</span>{/if}
</li>

<style>
  .row {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    min-height: 64px;
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--line);
  }
  .tile {
    flex: none;
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-tile);
    background: var(--raised);
    color: var(--text);
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .title {
    font-size: 17px;
    line-height: 24px;
    font-weight: 500;
    overflow-wrap: anywhere;
  }
  .subtitle {
    color: var(--muted);
  }
  .error {
    color: var(--error);
    font-size: 13px;
    line-height: 18px;
    overflow-wrap: anywhere;
  }
  .trailing {
    flex: none;
  }
</style>
