<script lang="ts">
  import type { Snippet } from "svelte";
  import { prefs } from "../lib/prefs.svelte";
  import { isRigSection } from "../lib/rigsections";
  import Chip, { type Tone } from "./Chip.svelte";
  import Icon from "./Icon.svelte";

  // A section whose header opens and closes it: one of Rig's rows, or one of
  // Tonight's cards. Closed, the header still says how it stands: a summary, and a
  // chip when something needs a look (docs/ux.md §7, "Rig", and §1).
  let {
    id,
    title,
    summary,
    status,
    scope = "rig",
    open: given,
    ontoggle,
    children,
  }: {
    id: string;
    title: string;
    // A line under the title while closed ("15 GB free").
    summary?: string | null;
    // Shown open or closed: a problem never hides in a closed section.
    status?: { tone: Tone; text: string } | null;
    // Rig's rows keep their open state in the browser themselves; Tonight's cards
    // are given theirs (Tonight decides where its checklist goes and whether it is open).
    scope?: "rig" | "tonight";
    open?: boolean;
    ontoggle?: (open: boolean) => void;
    children: Snippet;
  } = $props();

  const open = $derived(given ?? (isRigSection(id) && prefs.sectionOpen(id)));
  const key = $derived(`${scope}-${id}`);

  function toggle(): void {
    if (ontoggle) ontoggle(!open);
    else if (isRigSection(id)) prefs.setSectionOpen(id, !open);
  }
</script>

<section class="section" class:card={scope === "tonight"} id={key} aria-labelledby="{key}-title">
  <svelte:element this={scope === "tonight" ? "h2" : "h3"} class="head">
    <button type="button" aria-expanded={open} aria-controls="{key}-body" onclick={toggle}>
      <span class="text">
        <span class="heading" id="{key}-title">{title}</span>
        {#if summary && !open}<span class="summary">{summary}</span>{/if}
      </span>
      {#if status}<Chip tone={status.tone}>{status.text}</Chip>{/if}
      <span class="chevron" class:open aria-hidden="true"><Icon name="chevronDown" /></span>
    </button>
  </svelte:element>
  <!-- Hidden rather than removed: what is typed or running inside survives closing it. -->
  <div class="body" id="{key}-body" hidden={!open}>
    {@render children()}
  </div>
</section>

<style>
  .section:not(.card) + :global(.section) {
    border-top: 1px solid var(--line);
  }
  /* A card's own padding stands in for the row's. */
  .card {
    padding-top: 0;
    padding-bottom: 0;
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
