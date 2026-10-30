<script lang="ts">
  // Tabs whose content comes in later stages (2.7 Live, phases 3–5).
  import Button from "../components/Button.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import RigStatus from "../components/RigStatus.svelte";
  import ScreenHeader from "../components/ScreenHeader.svelte";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { router } from "../lib/router.svelte";

  let { tab }: { tab: "tonight" | "live" | "plan" | "session" } = $props();

  const t = $derived(i18n.t);
  const connected = $derived(live.app.equipment?.connection === "connected");
</script>

<ScreenHeader title={t.tabs[tab]}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

{#if tab === "tonight" && !connected}
  <EmptyState icon={tab} title={t.empty.tonight.title} body="{t.empty.tonight.body} {t.empty.tonight.connect}">
    {#snippet action()}
      <Button variant="primary" onclick={() => router.go({ screen: "rig" })}>{t.empty.openRig}</Button>
    {/snippet}
  </EmptyState>
{:else}
  <EmptyState icon={tab} title={t.empty[tab].title} body={t.empty[tab].body} />
{/if}
