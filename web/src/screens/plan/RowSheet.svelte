<script lang="ts">
  // One row of the exposure plan: filter, exposure, frames, and the camera
  // settings it takes (empty: as the camera is set). Edits apply as they are made.
  import { untrack } from "svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import { i18n } from "../../lib/i18n";
  import type { PlanRow } from "../../lib/types";

  let {
    row,
    filters,
    canRemove,
    onremove,
    onclose,
  }: {
    row: PlanRow;
    filters: string[];
    canRemove: boolean;
    onremove: () => void;
    onclose: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const NONE = "\u0000";

  const initial = untrack(() => ({ ...row }));
  let exposure: number | null = $state(initial.exposure);
  let count: number | null = $state(initial.count);
  let gain: number | null = $state(initial.gain ?? null);
  let offset: number | null = $state(initial.offset ?? null);
  $effect(() => {
    if (exposure !== null) row.exposure = exposure;
  });
  $effect(() => {
    if (count !== null) row.count = count;
  });
  $effect(() => {
    row.gain = gain;
    row.offset = offset;
  });
</script>

<Sheet title={t.sequence.row.title} {onclose}>
  <div class="fields">
    {#if filters.length || row.filter}
      <div class="group">
        <span class="label muted">{t.sequence.row.filter}</span>
        <SegmentedControl
          label={t.sequence.row.filter}
          options={[
            ...filters.map((name) => ({ value: name, label: name })),
            ...(row.filter && !filters.includes(row.filter) ? [{ value: row.filter, label: row.filter }] : []),
            { value: NONE, label: t.sequence.row.none },
          ]}
          value={row.filter ?? NONE}
          onchange={(value) => (row.filter = value === NONE ? null : value)} />
      </div>
    {/if}
    <NumberField label={t.sequence.row.exposure} bind:value={exposure} min={0.001} max={7200} unit="s" />
    <Stepper label={t.sequence.row.count} bind:value={count} min={1} max={10000} />
    <NumberField label={t.sequence.row.gain} bind:value={gain} min={0} max={10000} hint={t.sequence.row.settingHint} />
    <NumberField label={t.sequence.row.offset} bind:value={offset} min={0} max={10000} hint={t.sequence.row.settingHint} />
    <div class="group">
      <span class="label muted">{t.sequence.row.binning}</span>
      <SegmentedControl
        label={t.sequence.row.binning}
        options={[
          { value: "", label: t.sequence.row.cameras },
          ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n}×${n}` })),
        ]}
        value={row.binning ? String(row.binning) : ""}
        onchange={(value) => (row.binning = value ? Number(value) : null)} />
    </div>
  </div>
  {#snippet actions()}
    {#if canRemove}
      <ConfirmButton label={t.sequence.row.remove} confirmLabel={t.sequence.row.removeConfirm} onconfirm={onremove} />
    {/if}
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
    font-size: 13px;
    line-height: 18px;
  }
</style>
