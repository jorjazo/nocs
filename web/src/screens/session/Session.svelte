<script lang="ts">
  // The Session tab: the sequence's monitor (stage 5.14) above the night's saved
  // frames and their downloads, which only the owner's devices may list (ADR 0014).
  // On a PC the page is wide (docs/ux.md §7): the past sessions sit beside the frames.
  import Button from "../../components/Button.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import { auth } from "../../lib/auth.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import Monitor from "./Monitor.svelte";
  import NightFrames from "./NightFrames.svelte";
  import PastSessions from "./PastSessions.svelte";

  const t = $derived(i18n.t);
  const run = $derived(live.app.sequence?.run ?? null);
</script>

<ScreenHeader title={t.tabs.session}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

{#if run}
  <Monitor {run} />
  {#if run.state === "finished" && auth.owner}
    <div class="again">
      <Button variant="text" onclick={() => router.go({ screen: "sequence" })}>{t.session.newSequence}</Button>
    </div>
  {/if}
{:else if auth.owner}
  <EmptyState icon="session" title={t.session.noSession} body={t.session.noSessionBody}>
    {#snippet action()}
      <Button onclick={() => router.go({ screen: "sequence" })}>{t.session.openBuilder}</Button>
    {/snippet}
  </EmptyState>
{/if}

{#if auth.owner}
  <div class="archive">
    <div class="past"><PastSessions /></div>
    <div class="frames"><NightFrames /></div>
  </div>
{:else if !run}
  <EmptyState icon="session" title={t.nights.ownerOnly} body={t.nights.ownerOnlyBody} />
{/if}

<style>
  .again {
    margin-top: var(--space-2);
  }
  .past,
  .frames {
    margin-top: var(--space-6);
    min-width: 0;
  }
  /* A PC (the page is wide, docs/ux.md §7): the past sessions beside the night's
     frames rather than two lists the page's whole width. */
  @media (min-width: 1200px) {
    .archive {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
      column-gap: var(--space-8);
      align-items: start;
    }
    /* No past sessions yet: the frames alone. */
    .archive:has(> .past:empty) {
      grid-template-columns: minmax(0, 1fr);
    }
    .past:empty {
      display: none;
    }
  }
</style>
