<script lang="ts">
  // One group of a sequence: what kind of frames, the filter, the exposure (found for
  // flats, the camera's shortest for bias), how many, and the camera settings it
  // takes (empty: as the camera is set). Its temperature when cooling is per group.
  // Edits apply as they are made.
  import { untrack } from "svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { DEFAULT_EXPOSURE, fitGroup, type FrameKind } from "../../lib/sequence";
  import type { Group } from "../../lib/types";

  let {
    group,
    filters,
    perGroupCooling,
    canRemove,
    onremove,
    onclose,
  }: {
    group: Group;
    filters: string[];
    perGroupCooling: boolean;
    canRemove: boolean;
    onremove: () => void;
    onclose: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  // What an empty field means: the camera's value when the group starts, not now's.
  function now(value: number | null | undefined): string | null {
    return value == null ? null : formatPlain(value, i18n.locale);
  }
  const NONE = "\u0000";

  const initial = untrack(() => ({ ...group }));
  let exposure: number | null = $state(initial.exposure ?? null);
  let count: number | null = $state(initial.count);
  let gain: number | null = $state(initial.gain ?? null);
  let offset: number | null = $state(initial.offset ?? null);
  let temperature: number | null = $state(initial.temperature ?? null);
  const kind = $derived(group.frame_type ?? "light");
  const auto = $derived(kind === "flat" && group.exposure == null);
  const filtered = $derived(kind === "light" || kind === "flat");

  $effect(() => {
    if (exposure !== null && (kind === "light" || kind === "dark" || (kind === "flat" && !auto))) group.exposure = exposure;
  });
  $effect(() => {
    if (count !== null) group.count = kind === "flat" && auto ? Math.min(count, 200) : count;
  });
  $effect(() => {
    group.gain = gain;
    group.offset = offset;
  });
  $effect(() => {
    if (perGroupCooling) group.temperature = temperature;
  });

  function setKind(next: FrameKind): void {
    Object.assign(group, fitGroup({ ...$state.snapshot(group), frame_type: next, exposure: next === "flat" ? null : (exposure ?? DEFAULT_EXPOSURE) }));
    if (group.exposure != null) exposure = group.exposure;
  }
</script>

<Sheet title={s.row.title} {onclose}>
  <div class="fields">
    <div class="group">
      <span class="label muted">{s.row.kind}</span>
      <SegmentedControl
        label={s.row.kind}
        options={(["light", "dark", "bias", "flat"] as const).map((value) => ({ value, label: s.kinds[value] }))}
        value={kind}
        onchange={setKind} />
    </div>
    {#if filtered && (filters.length || group.filter)}
      <div class="group">
        <span class="label muted">{s.row.filter}</span>
        <SegmentedControl
          label={s.row.filter}
          options={[
            ...filters.map((name) => ({ value: name, label: name })),
            ...(group.filter && !filters.includes(group.filter) ? [{ value: group.filter, label: group.filter }] : []),
            { value: NONE, label: s.row.none },
          ]}
          value={group.filter ?? NONE}
          onchange={(value) => (group.filter = value === NONE ? null : value)} />
      </div>
    {/if}
    {#if kind === "flat"}
      <Toggle
        label={s.row.autoExposure}
        hint={s.row.autoExposureHint}
        checked={auto}
        onchange={(on) => (group.exposure = on ? null : (exposure ?? 1))} />
    {/if}
    {#if kind === "bias"}
      <p class="muted small">{s.row.biasExposure}</p>
    {:else if !auto}
      <NumberField label={s.row.exposure} bind:value={exposure} min={0.001} max={7200} unit="s" />
    {/if}
    <Stepper label={s.row.count} bind:value={count} min={1} max={auto ? 200 : 10000} />
    {#if perGroupCooling}
      <NumberField label={s.row.temperature} bind:value={temperature} min={-60} max={40} unit="°C" hint={s.row.temperatureHint} />
    {/if}
    <NumberField label={s.row.gain} bind:value={gain} min={0} max={10000} hint={s.row.settingHint(now(camera?.gain))} />
    <NumberField label={s.row.offset} bind:value={offset} min={0} max={10000} hint={s.row.settingHint(now(camera?.offset))} />
    <div class="group">
      <span class="label muted">{s.row.binning}</span>
      <SegmentedControl
        label={s.row.binning}
        options={[
          { value: "", label: s.row.cameras },
          ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n}×${n}` })),
        ]}
        value={group.binning ? String(group.binning) : ""}
        onchange={(value) => (group.binning = value ? Number(value) : null)} />
    </div>
  </div>
  {#snippet actions()}
    {#if canRemove}
      <ConfirmButton label={s.row.remove} confirmLabel={s.row.removeConfirm} onconfirm={onremove} />
    {/if}
    <Button variant="primary" onclick={onclose}>{s.row.done}</Button>
  {/snippet}
</Sheet>

<style>
  .fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .label {
    font-size: 13px;
    line-height: 18px;
  }
  .small {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
  }
</style>
