<script lang="ts">
  // The Session tab. The sequence monitor (phase 5) goes above; for now it
  // holds the night's saved frames and their downloads, which only the owner's
  // devices may list (ADR 0014).
  import EmptyState from "../../components/EmptyState.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import { auth } from "../../lib/auth.svelte";
  import { i18n } from "../../lib/i18n";
  import NightFrames from "./NightFrames.svelte";

  const t = $derived(i18n.t);
</script>

<ScreenHeader title={t.tabs.session}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

{#if auth.owner}
  <NightFrames />
{:else}
  <EmptyState icon="session" title={t.nights.ownerOnly} body={t.nights.ownerOnlyBody} />
{/if}
