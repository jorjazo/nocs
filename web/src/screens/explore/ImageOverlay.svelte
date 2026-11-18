<script lang="ts">
  // What lies over the image of Explore and Sequences: the tools at the top left
  // (guiding, focus), and at the right the screen's buttons (theme, show or hide the
  // tools, expand) over the right side's own widgets (go to, the sequence). Lying
  // down they are two columns that scroll when taller than the image; upright one
  // column, the buttons first.
  import type { Snippet } from "svelte";
  import Icon from "../../components/Icon.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import { i18n } from "../../lib/i18n";

  let {
    portrait,
    overlays,
    expanded,
    wide = false,
    ontoggleoverlays,
    ontoggleexpanded,
    tools,
    side,
  }: {
    portrait: boolean;
    overlays: boolean;
    expanded: boolean;
    // The right side's widget is open: upright, the tools give way to it.
    wide?: boolean;
    ontoggleoverlays: () => void;
    ontoggleexpanded: () => void;
    tools?: Snippet;
    side?: Snippet;
  } = $props();

  const t = $derived(i18n.t);
</script>

<div class="overlay" class:portrait class:wide>
  <div class="tools">
    {#if overlays}{@render tools?.()}{/if}
  </div>
  <div class="buttons">
    <div class="row">
      {#if overlays}<span class="theme"><ThemeButton /></span>{/if}
      <button
        type="button"
        class="icon-button"
        aria-label={overlays ? t.live.overlaysHide : t.live.overlaysShow}
        aria-pressed={!overlays}
        onclick={ontoggleoverlays}>
        <Icon name={overlays ? "eye" : "eyeOff"} />
      </button>
      <button
        type="button"
        class="icon-button"
        aria-label={expanded ? t.live.shrink : t.live.expand}
        aria-pressed={expanded}
        onclick={ontoggleexpanded}>
        <Icon name={expanded ? "shrink" : "expand"} />
      </button>
    </div>
    {#if overlays}{@render side?.()}{/if}
  </div>
</div>

<style>
  .overlay {
    position: absolute;
    left: 0;
    right: 0;
    top: env(safe-area-inset-top);
    bottom: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    gap: var(--space-2);
    padding: var(--space-3);
    pointer-events: none;
  }
  .overlay :global(button),
  .overlay :global(a),
  .overlay :global([data-overlay]),
  .overlay :global(dialog) {
    pointer-events: auto;
  }
  /* Upright, one column: the buttons (and the side's widget) first, then the tools on
     the left; one tool is open at a time, as wide as the image. */
  .portrait {
    display: flex;
    flex-direction: column;
  }
  /* The side holding the open tool gives way when the image is short. */
  .portrait .buttons {
    order: -1;
    flex: 0 0 auto;
  }
  .portrait .tools {
    flex: 0 1 auto;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .portrait.wide .buttons {
    flex-shrink: 1;
  }
  .portrait.wide .tools {
    flex-shrink: 0;
  }
  .portrait .buttons :global(.card),
  .portrait .tools :global(.card) {
    width: 100%;
  }
  .tools,
  .buttons {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .buttons {
    align-items: flex-end;
  }
  .tools {
    align-items: flex-start;
  }
  .row {
    display: flex;
    gap: var(--space-2);
  }
  .icon-button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    color: var(--text);
    cursor: pointer;
  }
  /* The navigation rail carries the theme button on wide screens. */
  @media (min-width: 768px) {
    .theme {
      display: none;
    }
  }
</style>
