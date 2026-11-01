<script lang="ts" module>
  export type SheetKind = "focus" | "pointing" | "dither" | "night" | "cooling" | "end";
</script>

<script lang="ts">
  // The builder's behaviours, one sheet each: when to focus, the night's window,
  // cooling, and what happens when the session ends. Edits apply as they are made.
  import { untrack } from "svelte";
  import Button from "../../components/Button.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import type { PowerOutput, Template } from "../../lib/types";

  let {
    kind,
    template,
    outputs,
    canCool,
    onclose,
  }: {
    kind: SheetKind;
    template: Template;
    outputs: PowerOutput[];
    canCool: boolean;
    onclose: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const title = $derived(
    { focus: s.autofocus, pointing: s.pointing, dither: s.dither, night: s.night, cooling: s.cooling, end: s.whenFinished }[kind],
  );

  const focus = $derived(
    template.focus ?? { at_start: false, filter_change: false, temperature_change: null, hfr_increase: null, minutes: null },
  );
  // Numbers edited here; null is "empty" (no such reason, no limit).
  const initial = untrack(() => $state.snapshot(template));
  let temperature: number | null = $state(initial.focus?.temperature_change ?? null);
  let hfr: number | null = $state(initial.focus?.hfr_increase != null ? initial.focus.hfr_increase * 100 : null);
  let minutes: number | null = $state(initial.focus?.minutes ?? null);
  let altitude: number | null = $state(initial.min_altitude ?? null);
  let cooling: number | null = $state(initial.cooling ?? -10);
  let ramp: number | null = $state(initial.cooling_ramp ?? null);
  let every: number | null = $state(initial.dither_every ?? 3);
  let checkEvery: number | null = $state(initial.recenter_every ?? 10);
  let drift: number | null = $state(initial.recenter_drift ?? 2);
  const solver = $derived(live.app.solver?.available === true);
  let pixels: number | null = $state(initial.dither_pixels ?? 5);

  function setFocus(change: Partial<NonNullable<Template["focus"]>>): void {
    template.focus = { ...focus, ...change };
  }
  $effect(() => {
    if (kind !== "focus") return;
    setFocus({ temperature_change: temperature, hfr_increase: hfr !== null ? hfr / 100 : null, minutes });
  });
  $effect(() => {
    if (kind === "night") template.min_altitude = altitude;
  });
  $effect(() => {
    if (kind !== "pointing") return;
    if (drift !== null) template.recenter_drift = drift;
    if (template.recenter_every != null && checkEvery !== null) template.recenter_every = checkEvery;
  });
  $effect(() => {
    if (kind !== "dither") return;
    if (pixels !== null) template.dither_pixels = pixels;
    if (template.dither_every != null && every !== null) template.dither_every = every;
  });
  $effect(() => {
    if (kind !== "cooling") return;
    template.cooling_ramp = ramp;
    if (template.cooling != null && cooling !== null) template.cooling = cooling;
  });

  const end = $derived(template.end ?? { park: true, warm: true, outputs: [] });
  function setEnd(change: Partial<NonNullable<Template["end"]>>): void {
    template.end = { ...end, ...change };
  }
  function toggleOutput(id: string, off: boolean): void {
    const now = end.outputs ?? [];
    setEnd({ outputs: off ? [...now, id] : now.filter((o) => o !== id) });
  }
</script>

<Sheet {title} {onclose}>
  <div class="fields">
    {#if kind === "focus"}
      <Toggle label={s.focusSheet.atStart} hint={s.focusSheet.atStartHint} checked={focus.at_start !== false} onchange={(on) => setFocus({ at_start: on })} />
      <Toggle
        label={s.focusSheet.filterChange}
        hint={s.focusSheet.filterChangeHint}
        checked={focus.filter_change ?? false}
        onchange={(on) => setFocus({ filter_change: on })} />
      <NumberField label={s.focusSheet.temperature} bind:value={temperature} min={0.1} max={20} unit="°C" hint={s.focusSheet.emptyOff} />
      <NumberField label={s.focusSheet.hfr} bind:value={hfr} min={1} max={200} unit="%" hint={s.focusSheet.hfrHint} />
      <NumberField label={s.focusSheet.minutes} bind:value={minutes} min={1} max={600} unit="min" hint={s.focusSheet.emptyOff} />
    {:else if kind === "pointing"}
      {#if !solver}<p class="muted">{s.pointingSheet.noSolver}</p>{/if}
      <Toggle
        label={s.pointingSheet.center}
        hint={s.pointingSheet.centerHint}
        checked={template.center ?? false}
        disabled={!solver && !template.center}
        onchange={(on) => {
          template.center = on;
          if (!on) template.recenter_every = null;
        }} />
      {#if template.center}
        <Toggle
          label={s.pointingSheet.check}
          hint={s.pointingSheet.checkHint}
          checked={template.recenter_every != null}
          onchange={(on) => (template.recenter_every = on ? (checkEvery ?? 10) : null)} />
        {#if template.recenter_every != null}
          <Stepper label={s.pointingSheet.every} bind:value={checkEvery} min={1} max={200} unit={t.sequence.row.count.toLowerCase()} />
          <NumberField label={s.pointingSheet.drift} bind:value={drift} min={0.1} max={60} unit="′" />
        {/if}
      {/if}
    {:else if kind === "dither"}
      <Toggle
        label={s.ditherSheet.on}
        hint={s.ditherSheet.onHint}
        checked={template.dither_every != null}
        onchange={(on) => (template.dither_every = on ? (every ?? 3) : null)} />
      {#if template.dither_every != null}
        <Stepper label={s.ditherSheet.every} bind:value={every} min={1} max={50} unit={t.sequence.row.count.toLowerCase()} />
        <NumberField label={s.ditherSheet.pixels} bind:value={pixels} min={0.5} max={50} unit="px" hint={s.ditherSheet.pixelsHint} />
      {/if}
    {:else if kind === "night"}
      <Toggle
        label={s.nightSheet.startAtDusk}
        hint={s.nightSheet.startAtDuskHint}
        checked={template.start_at_dusk !== false}
        onchange={(on) => (template.start_at_dusk = on)} />
      <Toggle
        label={s.nightSheet.untilDawn}
        hint={s.nightSheet.untilDawnHint}
        checked={template.until_dawn !== false}
        onchange={(on) => (template.until_dawn = on)} />
      <div class="group">
        <span class="label muted">{s.nightSheet.darkness}</span>
        <SegmentedControl
          label={s.nightSheet.darkness}
          options={[
            { value: "civil", label: s.nightSheet.civil },
            { value: "nautical", label: s.nightSheet.nautical },
            { value: "astronomical", label: s.nightSheet.astronomical },
          ]}
          value={template.darkness ?? "astronomical"}
          onchange={(value) => (template.darkness = value)} />
      </div>
      <NumberField label={s.nightSheet.minAltitude} bind:value={altitude} min={0} max={90} unit="°" hint={s.nightSheet.minAltitudeHint} />
    {:else if kind === "cooling"}
      {#if !canCool}<p class="muted">{s.coolingSheet.cannot}</p>{/if}
      <Toggle
        label={s.coolingSheet.on}
        checked={template.cooling != null}
        disabled={!canCool && template.cooling == null}
        onchange={(on) => (template.cooling = on ? (cooling ?? -10) : null)} />
      {#if template.cooling != null}
        <NumberField label={s.coolingSheet.temperature} bind:value={cooling} min={-60} max={40} unit="°C" />
        <NumberField label={s.coolingSheet.ramp} bind:value={ramp} min={0} max={60} unit="°C/min" hint={s.coolingSheet.rampHint} />
      {/if}
    {:else}
      <Toggle label={s.endSheet.park} checked={end.park !== false} onchange={(on) => setEnd({ park: on })} />
      <Toggle label={s.endSheet.warm} hint={s.endSheet.warmHint} checked={end.warm !== false} onchange={(on) => setEnd({ warm: on })} />
      {#if outputs.length}
        <h3 class="label muted">{s.endSheet.outputs}</h3>
        {#each outputs as output (output.id)}
          <Toggle
            label={output.label || output.id}
            checked={end.outputs?.includes(output.id) ?? false}
            onchange={(off) => toggleOutput(output.id, off)} />
        {/each}
      {/if}
    {/if}
  </div>
  {#snippet actions()}
    <Button variant="primary" onclick={onclose}>{t.sequence.row.done}</Button>
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
    margin: var(--space-2) 0 0;
    font-size: 13px;
    line-height: 18px;
    font-weight: 400;
  }
</style>
