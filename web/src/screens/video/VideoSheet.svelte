<script lang="ts">
  // Editor for the video's exposure (in milliseconds, with common ones a tap away) or
  // its gain, opened from their tiles. The stream takes either at once.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import { setVideoSettings } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { CameraState, VideoSettingsRequest, VideoState } from "../../lib/types";

  let {
    setting,
    video,
    camera,
    onclose,
  }: { setting: "exposure" | "gain"; video: VideoState; camera: CameraState; onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const PRESETS_MS = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];

  const range = $derived(camera.video?.exposure_range ?? { min: 0.00001, max: 60 });
  const initial = untrack(() => ({ exposure: video.exposure * 1000, gain: video.gain ?? camera.gain }));
  let milliseconds = $state<number | null>(initial.exposure);
  let gain = $state<number | null>(initial.gain);
  let busy = $state(false);
  let error = $state("");

  async function apply(body: VideoSettingsRequest): Promise<void> {
    busy = true;
    error = "";
    try {
      await setVideoSettings(body);
      onclose();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  function submit(): void {
    if (setting === "exposure" && milliseconds !== null) void apply({ exposure: milliseconds / 1000 });
    else if (setting === "gain" && gain !== null) void apply({ gain });
  }
</script>

<Sheet title={setting === "exposure" ? t.video.exposure : t.video.gain} {onclose}>
  {#if setting === "exposure"}
    <Stepper
      label={t.video.milliseconds}
      bind:value={milliseconds}
      min={range.min * 1000}
      max={range.max * 1000}
      step={1}
      unit="ms" />
    <div class="presets" role="group" aria-label={t.video.presets}>
      {#each PRESETS_MS.filter((ms) => ms >= range.min * 1000 && ms <= range.max * 1000) as ms (ms)}
        <button
          type="button"
          class="preset"
          aria-pressed={Math.abs(video.exposure * 1000 - ms) < 1e-6}
          onclick={() => void apply({ exposure: ms / 1000 })}>
          {formatPlain(ms, locale)} ms
        </button>
      {/each}
    </div>
  {:else if camera.gain_range}
    <Stepper label={t.video.gain} bind:value={gain} min={camera.gain_range.min} max={camera.gain_range.max} />
  {/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {#snippet actions()}
    <Button variant="primary" {busy} disabled={setting === "exposure" ? milliseconds === null : gain === null} onclick={submit}>
      {t.live.apply}
    </Button>
  {/snippet}
</Sheet>

<style>
  .presets {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
    gap: var(--space-2);
  }
  .preset {
    min-height: var(--touch);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    font-size: 15px;
    cursor: pointer;
  }
  .preset[aria-pressed="true"] {
    border-color: var(--accent);
    color: var(--accent);
    font-weight: 600;
  }
</style>
