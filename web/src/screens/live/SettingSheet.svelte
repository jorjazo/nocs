<script lang="ts" module>
  export type Setting = "exposure" | "gain" | "offset" | "binning" | "frame" | "cooling";
</script>

<script lang="ts">
  // Editor for one exposure setting, opened from its tile. Choices from a short
  // list apply on tap; typed numbers apply with the button.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { setCameraSettings, setCooling } from "../../lib/api";
  import { capture, MAX_EXPOSURE } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { CameraRoleName, CameraSettingsRequest, CameraState, FrameTypeName } from "../../lib/types";

  let {
    setting,
    role,
    camera,
    onclose,
  }: { setting: Setting; role: CameraRoleName; camera: CameraState; onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const EXPOSURE_PRESETS = [0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 180, 300, 600];
  const FRAME_TYPES: readonly FrameTypeName[] = ["light", "dark", "flat", "bias"];

  // Drafts, from the values when the sheet opened.
  const initial = untrack(() => camera);
  let exposure = $state<number | null>(capture.exposure[untrack(() => role)]);
  let gain = $state<number | null>(initial.gain);
  let offset = $state<number | null>(initial.offset);
  let coolerOn = $state(initial.cooler ?? initial.target !== null);
  let target = $state<number | null>(initial.target ?? -10);
  let ramp = $state<number | null>(initial.ramp ?? 0);

  let busy = $state(false);
  let error = $state("");

  const title = $derived(setting === "cooling" ? t.live.cooling.title : t.live[setting]);

  async function apply(action: () => Promise<void>): Promise<void> {
    busy = true;
    error = "";
    try {
      await action();
      onclose();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  function settings(body: CameraSettingsRequest): Promise<void> {
    return apply(() => setCameraSettings(role, body));
  }

  function pickExposure(seconds: number): void {
    capture.setExposure(role, seconds);
    onclose();
  }

  const valid = $derived.by(() => {
    switch (setting) {
      case "exposure":
        return exposure !== null;
      case "gain":
        return gain !== null;
      case "offset":
        return offset !== null;
      case "cooling":
        return !coolerOn || (target !== null && ramp !== null);
      default:
        return true;
    }
  });

  function submit(): void {
    if (setting === "exposure" && exposure !== null) pickExposure(exposure);
    else if (setting === "gain" && gain !== null) void settings({ gain });
    else if (setting === "offset" && offset !== null) void settings({ offset });
    else if (setting === "cooling") {
      void apply(() =>
        setCooling(
          role,
          coolerOn ? { on: true, target: target ?? undefined, ramp: ramp ?? undefined } : { on: false },
        ),
      );
    }
  }
</script>

<Sheet {title} {onclose}>
  {#if setting === "exposure"}
    <Stepper label={t.live.seconds} bind:value={exposure} min={0} max={MAX_EXPOSURE} unit="s" />
    <div class="presets" role="group" aria-label={t.live.presets}>
      {#each EXPOSURE_PRESETS as seconds (seconds)}
        <button
          type="button"
          class="preset"
          aria-pressed={capture.exposure[role] === seconds}
          onclick={() => pickExposure(seconds)}>
          {formatSeconds(seconds, locale)}
        </button>
      {/each}
    </div>
  {:else if setting === "gain" && camera.gain_range}
    <Stepper label={t.live.gain} bind:value={gain} min={camera.gain_range.min} max={camera.gain_range.max} />
  {:else if setting === "offset" && camera.offset_range}
    <Stepper label={t.live.offset} bind:value={offset} min={camera.offset_range.min} max={camera.offset_range.max} />
  {:else if setting === "binning"}
    <SegmentedControl
      label={t.live.binning}
      options={Array.from({ length: camera.max_binning }, (_, i) => ({ value: String(i + 1), label: `${i + 1}×${i + 1}` }))}
      value={String(camera.binning[0])}
      onchange={(value) => void settings({ binning: Number(value) })} />
  {:else if setting === "frame"}
    <SegmentedControl
      label={t.live.frame}
      options={FRAME_TYPES.map((type) => ({ value: type, label: t.live.frameTypes[type] }))}
      value={camera.frame_type}
      onchange={(value) => void settings({ frame_type: value })} />
  {:else if setting === "cooling"}
    <div class="readouts">
      <div>
        <span class="label muted">{t.live.cooling.sensor}</span>
        <span class="readout">{camera.temperature === null ? "—" : formatTemperature(camera.temperature, locale)}</span>
      </div>
      <div>
        <span class="label muted">{t.live.cooling.power}</span>
        <span class="readout">{camera.cooler_power === null ? "—" : formatDecimal(camera.cooler_power, locale, 0)}</span>
      </div>
    </div>
    <Toggle label={t.live.cooling.on} checked={coolerOn} onchange={(checked) => (coolerOn = checked)} />
    {#if coolerOn}
      <Stepper label={t.live.cooling.target} bind:value={target} min={-60} max={40} unit="°C" />
      <Stepper label={t.live.cooling.ramp} bind:value={ramp} min={0} max={60} step={0.5} unit="°C/min" hint={t.live.cooling.rampHint} />
    {/if}
  {/if}

  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

  {#snippet actions()}
    {#if setting === "exposure" || setting === "gain" || setting === "offset" || setting === "cooling"}
      <Button variant="primary" {busy} disabled={!valid} onclick={submit}>{t.live.apply}</Button>
    {/if}
  {/snippet}
</Sheet>

<style>
  .presets {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .preset {
    min-height: var(--touch);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--raised);
    font-family: var(--font-mono);
    font-size: 15px;
    cursor: pointer;
  }
  .preset[aria-pressed="true"] {
    border-color: var(--accent);
    color: var(--accent);
  }
  .readouts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3);
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--raised);
  }
</style>
