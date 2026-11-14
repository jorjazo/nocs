<script lang="ts">
  import type { Snippet } from "svelte";
  import { prefs } from "../lib/prefs.svelte";
  import type { RigSection } from "../lib/rigsections";
  import Chip, { type Tone } from "./Chip.svelte";
  import Icon from "./Icon.svelte";

  // One of Rig's sections: its header opens and closes it, and the browser keeps
  // which are open. Closed, the header still says how it stands: a summary, and a
  // chip when something needs a look (docs/ux.md §7, "Rig").
  let {
    id,
    title,
    summary,
    status,
    children,
  }: {
    id: RigSection;
    title: string;
    // A line under the title while closed ("15 GB free").
    summary?: string | null;
    // Shown open or closed: a problem never hides in a closed section.
    status?: { tone: Tone; text: string } | null;
    children: Snippet;
  } = $props();

  const open = $derived(prefs.sectionOpen(id));
</script>

<section class="section" id="rig-{id}" aria-labelledby="rig-{id}-title">
  <h3 class="head">
    <button
      type="button"
      aria-expanded={open}
      aria-controls="rig-{id}-body"
      onclick={() => prefs.setSectionOpen(id, !open)}>
      <span class="text">
        <span class="heading" id="rig-{id}-title">{title}</span>
        {#if summary && !open}<span class="summary">{summary}</span>{/if}
      </span>
      {#if status}<Chip tone={status.tone}>{status.text}</Chip>{/if}
      <span class="chevron" class:open aria-hidden="true"><Icon name="chevronDown" /></span>
    </button>
  </h3>
  <!-- Hidden rather than removed: what is typed or running inside survives closing it. -->
  <div class="body" id="rig-{id}-body" hidden={!open}>
    {@render children()}
  </div>
</section>

<style>
  .section + :global(.section) {
    border-top: 1px solid var(--line);
  }
  .section {
    /* Room above a section a link scrolled to (#/rig/site): its group's title. */
    scroll-margin-top: var(--space-8);
  }
  .head {
    margin: 0;
    font: inherit;
  }
  button {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    min-height: 64px;
    padding: var(--space-3) 0;
    border: 0;
    background: none;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .text {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .summary {
    color: var(--muted);
    font-size: 15px;
    line-height: 20px;
    overflow-wrap: anywhere;
  }
  .chevron {
    display: inline-flex;
    flex: none;
    color: var(--muted);
    transition: transform 150ms ease;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .chevron {
      transition: none;
    }
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding-bottom: var(--space-4);
  }
  .body[hidden] {
    display: none;
  }
</style>
