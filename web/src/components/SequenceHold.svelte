<script lang="ts">
  // "Pause the sequence and do it" (design §6, ADR 0031): where a running
  // sequence holds a device this screen drives, say so and offer to pause it,
  // which lends the devices back; while it is paused, offer to resume it.
  import { pauseSequence, resumeSequence } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { href } from "../lib/router.svelte";
  import type { Role } from "../lib/types";
  import Banner from "./Banner.svelte";
  import Button from "./Button.svelte";

  let { resources }: { resources: Role[] } = $props();

  const t = $derived(i18n.t);
  const run = $derived(live.app.sequence?.run ?? null);
  // The sequence's job, while it holds one of these devices.
  const holds = $derived(
    Object.values(live.app.jobs ?? {}).some(
      (job) =>
        job.kind === "sequence" &&
        job.state === "running" &&
        !job.suspended &&
        job.resources.some((r) => (resources as string[]).includes(r)),
    ),
  );
  const shown = $derived(
    run && run.state !== "finished" && (holds || run.state === "paused" || run.state === "pausing") ? run.state : null,
  );

  let busy = $state(false);
  let error = $state("");

  async function act(call: () => Promise<void>): Promise<void> {
    busy = true;
    error = "";
    try {
      await call();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

{#if shown}
  <Banner icon="session" tone={shown === "paused" ? "neutral" : "warning"}>
    <a href={href({ screen: "session" })}>
      {shown === "paused" ? t.session.hold.paused : shown === "pausing" ? t.session.hold.pausing : t.session.hold.using}
    </a>
    {#if error}<br />{error}{/if}
    {#snippet action()}
      {#if auth.owner && shown === "paused"}
        <Button variant="text" {busy} onclick={() => void act(resumeSequence)}>{t.session.hold.resume}</Button>
      {:else if auth.owner && shown !== "pausing"}
        <Button variant="text" {busy} onclick={() => void act(() => pauseSequence({ now: true }))}>{t.session.hold.pause}</Button>
      {/if}
    {/snippet}
  </Banner>
{/if}

<style>
  a {
    color: inherit;
  }
</style>
