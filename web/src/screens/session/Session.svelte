<script lang="ts">
  // The Session tab: the night's saved frames and their downloads, which only the
  // owner's devices may list, and the past sessions. A running sequence is followed
  // in Sequences, a running plan in Plan.
  // On a PC the page is wide (docs/ux.md §5): the past sessions sit beside the frames.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import { auth } from "../../lib/auth.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import { isActive, isPlanRun } from "../../lib/sequence";
  import NightFrames from "./NightFrames.svelte";
  import PastSessions from "./PastSessions.svelte";

  const t = $derived(i18n.t);
  const run = $derived(live.app.sequence?.run ?? null);
  const active = $derived(isActive(run));
  const planRuns = $derived(isPlanRun(run));
</script>

<ScreenHeader title={t.tabs.session}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

{#if active}
  <div class="again">
    <Banner icon="sequence">
      {planRuns ? t.session.planRunning : t.session.running}
      {#snippet action()}
        <Button variant="text" onclick={() => router.go({ screen: planRuns ? "plan" : "sequence" })}>
          {planRuns ? t.session.openPlan : t.session.openSequences}
        </Button>
      {/snippet}
    </Banner>
  </div>
{/if}

{#if auth.owner}
  <div class="archive">
    <div class="past"><PastSessions /></div>
    <div class="frames"><NightFrames /></div>
  </div>
{:else}
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
  /* A PC (the page is wide, docs/ux.md §5): the past sessions beside the night's
     frames rather than two lists the page's whole width. */
  @media (min-width: 1200px) {
    .archive {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
      column-gap: var(--space-8);
      align-items: start;
    }
    /* No past sessions yet: the frames alone, the page's whole width. */
    .past:empty {
      display: none;
    }
    .past:empty + .frames {
      grid-column: 1 / -1;
    }
  }
</style>
