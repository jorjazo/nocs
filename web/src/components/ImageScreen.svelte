<script lang="ts">
  // The layout of the screens built around the latest image (Explore, Sequences): the
  // image fills the screen, with what goes under it (the histogram, the status bar);
  // the panel of actions sits at its side lying down, or is a sheet over the image
  // upright, whose dock (the primary actions) always shows. Pressing "expand" makes
  // the image take the whole screen.
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  let {
    portrait,
    expanded = false,
    alone = false,
    sheetOpen,
    stageLabel,
    panelLabel,
    openLabel,
    closeLabel,
    ontogglesheet,
    image,
    under,
    body,
    dock,
  }: {
    portrait: boolean;
    expanded?: boolean;
    // Without the tabs (a visitor's only screen): the whole height.
    alone?: boolean;
    sheetOpen: boolean;
    stageLabel: string;
    panelLabel: string;
    openLabel: string;
    closeLabel: string;
    ontogglesheet: () => void;
    image: Snippet;
    under?: Snippet;
    body: Snippet;
    dock: Snippet;
  } = $props();
</script>

<div class="screen" class:portrait class:landscape={!portrait} class:expanded class:alone>
  <section class="stage" aria-label={stageLabel}>
    <div class="image">{@render image()}</div>
    {@render under?.()}
  </section>

  <section class="panel" class:open={sheetOpen} aria-label={panelLabel}>
    <div class="body">{@render body()}</div>
    <!-- The actions stay in reach while the panel scrolls, or while its sheet is
         folded on an upright screen. -->
    <div class="dock">
      {#if portrait}
        <button type="button" class="handle" aria-expanded={sheetOpen} onclick={ontogglesheet}>
          <Icon name={sheetOpen ? "chevronDown" : "up"} size={18} />
          {sheetOpen ? closeLabel : openLabel}
        </button>
      {/if}
      {@render dock()}
    </div>
  </section>
</div>

<style>
  /* The screen's height without the tab bar (phones) or the rail (from 768 px). */
  .screen {
    --available: calc(100dvh - var(--tabbar-height) - env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    height: var(--available);
  }
  @media (min-width: 768px) {
    .screen {
      --available: 100dvh;
    }
  }
  .screen.alone {
    --available: 100dvh;
  }
  .landscape {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(300px, 32vw, 400px);
  }
  .stage {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    flex: 1 1 auto;
  }
  .image {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
  }
  .expanded .stage {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: #000;
  }

  /* The panel: a column at the image's side, scrolling, with its actions at the foot. */
  .panel {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--bg);
  }
  .landscape .panel {
    border-left: 1px solid var(--line);
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-4) var(--space-3);
  }
  .landscape .body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
  }
  /* Upright: the actions under the image, the rest in a sheet that opens over it. */
  .portrait .panel {
    position: relative;
    flex: none;
  }
  .portrait .body {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 100%;
    z-index: 4;
    max-height: calc(var(--available) * 0.62);
    overflow-y: auto;
    border-top: 1px solid var(--line);
    background: var(--bg);
    box-shadow: 0 -8px 24px rgb(0 0 0 / 40%);
  }
  .portrait .panel:not(.open) .body {
    display: none;
  }
  .handle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-height: 32px;
    border: 0;
    background: transparent;
    color: var(--muted);
    font-size: 14px;
    cursor: pointer;
  }
  .dock {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4) var(--space-3);
    border-top: 1px solid var(--line);
    background: var(--bg);
  }
</style>
