<script lang="ts">
  // The Sun and Moon finder in the mount's sheet (ADR 0049): find either by its
  // brightness, around its position or around where the mount points. The Sun, and
  // anything near it, asks for the Sun's warning first, once a day.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { ApiError, findBody } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { goRefusal } from "../../lib/goto";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import type { FinderState, MountState } from "../../lib/types";
  import FinderCard from "./FinderCard.svelte";
  import SunWarning from "./SunWarning.svelte";

  type Body = FinderState["body"];

  let { mount, guiding, busyMount }: { mount: MountState; guiding: boolean; busyMount: boolean } = $props();

  const t = $derived(i18n.t);
  const finder = $derived(live.app.finder ?? null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);

  let radius = $state<number | null>(5);
  let radiusValid = $state(true);
  let here = $state(false);
  let busy = $state<Body | null>(null);
  let error = $state("");
  // A body refused near the Sun, to find once its warning is acknowledged.
  let warned = $state<Body | null>(null);

  const reason = $derived.by((): string | null => {
    if (!auth.owner) return t.mount.locked;
    if (!camera) return t.finder.noCamera;
    if (holder(live.app.jobs, "main_camera")) return t.finder.cameraBusy;
    if (!camera.field) return t.finder.noField;
    return null;
  });
  const disabled = $derived(reason !== null || busyMount || mount.parked || !radiusValid || busy !== null);

  async function find(body: Body, acknowledged = false): Promise<void> {
    if (body === "sun" && !mount.sun_acknowledged && !acknowledged) {
      warned = body;
      return;
    }
    busy = body;
    error = "";
    try {
      await findBody({ body, radius: radius ?? 5, here, stop_guiding: guiding });
    } catch (e) {
      if (e instanceof ApiError && goRefusal(e.status, e.message) === "sun") warned = body;
      else error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  function acknowledged(): void {
    const body = warned;
    warned = null;
    if (body) void find(body, true);
  }
</script>

<section class="group" aria-labelledby="finder-title">
  <h3 class="label muted" id="finder-title">{t.finder.title}</h3>
  <p class="caption muted">{t.finder.hint}</p>
  <NumberField label={t.finder.radius} bind:value={radius} bind:valid={radiusValid} min={0} max={30} unit="°" />
  <Toggle label={t.finder.here} hint={t.finder.hereHint} checked={here} onchange={(on) => (here = on)} />
  <div class="buttons">
    <Button {disabled} busy={busy === "moon"} onclick={() => void find("moon")}>{t.finder.findMoon}</Button>
    <Button {disabled} busy={busy === "sun"} onclick={() => void find("sun")}>{t.finder.findSun}</Button>
  </div>
  {#if reason}
    <p class="caption muted">{reason}</p>
  {:else if guiding}
    <p class="caption muted">{t.finder.guidingStops}</p>
  {/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {#if finder}<FinderCard {finder} />{/if}
</section>

{#if warned}
  <SunWarning onclose={() => (warned = null)} onacknowledged={acknowledged} />
{/if}

<style>
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h3,
  p {
    margin: 0;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .buttons > :global(*) {
    flex: 1 1 140px;
  }
</style>
