<script lang="ts">
  // A popup when a job fails because the camera sent no image (an exposure the driver
  // gave up on, a video without frames): what failed and what to check, the Pi's
  // limited USB ports first when they power something at risk. Mounted once, for the
  // owner, on every screen: it shows failures it saw happen, not old ones.
  import { cameraLinkCauses, jobStates, newCameraFaults, type JobStates } from "../lib/camerafault";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import Banner from "./Banner.svelte";
  import Button from "./Button.svelte";
  import Sheet from "./Sheet.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  let before: JobStates | null = null;
  let shown = $state<string | null>(null);

  $effect(() => {
    const jobs = live.synced ? (live.app.jobs ?? {}) : null;
    // Reads every job's state, so the effect runs again when one changes.
    const states = jobStates(jobs);
    const found = newCameraFaults(before, jobs);
    before = states;
    const last = found.at(-1);
    if (last !== undefined) shown = jobs?.[last]?.error ?? "";
  });

  const causes = $derived(cameraLinkCauses(live.app.equipment?.usb_power, t, locale));
</script>

{#if shown !== null}
  <Sheet title={t.cameraLink.title} onclose={() => (shown = null)}>
    {#if shown}<Banner icon="alert" tone="error">{shown}</Banner>{/if}
    <p>{t.cameraLink.cause}</p>
    <ul>
      {#each causes as cause (cause)}<li>{cause}</li>{/each}
    </ul>
    {#snippet actions()}
      <Button variant="primary" onclick={() => (shown = null)}>{t.cameraLink.close}</Button>
    {/snippet}
  </Sheet>
{/if}

<style>
  p {
    margin: var(--space-3) 0 var(--space-2);
  }
  ul {
    margin: 0;
    padding-left: var(--space-6);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
