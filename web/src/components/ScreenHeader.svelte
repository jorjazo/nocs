<script lang="ts">
  import type { Snippet } from "svelte";
  import ThemeButton from "./ThemeButton.svelte";

  let {
    title,
    eyebrow,
    trailing,
  }: {
    title: string;
    // Context above the title, e.g. the active profile.
    eyebrow?: string;
    trailing?: Snippet;
  } = $props();
</script>

<!-- Phones: title and theme button, then the trailing controls on their own
     line (Spanish titles and chips do not fit side by side). Wide screens: one
     line, and the navigation rail carries the theme button. -->
<header class="header">
  <div class="titles">
    {#if eyebrow}<p class="eyebrow">{eyebrow}</p>{/if}
    <h1 class="display">{title}</h1>
  </div>
  <span class="theme"><ThemeButton /></span>
  {#if trailing}<div class="trailing">{@render trailing()}</div>{/if}
</header>

<style>
  .header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: "titles theme" "trailing trailing";
    align-items: center;
    column-gap: var(--space-3);
    row-gap: var(--space-2);
    padding: var(--space-6) 0 var(--space-4);
  }
  .titles {
    grid-area: titles;
    min-width: 0;
  }
  .eyebrow {
    color: var(--muted);
  }
  h1 {
    overflow-wrap: anywhere;
  }
  .theme {
    grid-area: theme;
  }
  .trailing {
    grid-area: trailing;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
  }
  @media (min-width: 768px) {
    .header {
      grid-template-areas: "titles trailing";
    }
    .theme {
      display: none;
    }
  }
</style>
