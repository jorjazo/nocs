<script lang="ts">
  // One line of a target's lights: the filter (none without a wheel), the exposure,
  // how many, and the camera settings it takes (empty: as the camera is set). The
  // frames it has stay the server's. Edits apply as they are made.
  import { untrack } from "svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import NumberField from "../../components/NumberField.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import type { PlanLine } from "../../lib/types";

  let {
    line,
    filters,
    onremove,
    onclose,
  }: {
    line: PlanLine;
    filters: string[];
    onremove: () => void;
    onclose: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  function now(value: number | null | undefined): string | null {
    return value == null ? null : formatPlain(value, i18n.locale);
  }
  const NONE = "\u0000";

  const initial = untrack(() => ({ ...line }));
  let exposure: number | null = $state(initial.exposure);
  let count: number | null = $state(initial.count);
  let gain: number | null = $state(initial.gain ?? null);
  let offset: number | null = $state(initial.offset ?? null);

  $effect(() => {
    if (exposure !== null) line.exposure = exposure;
  });
  $effect(() => {
    if (count !== null) line.count = count;
  });
  $effect(() => {
    line.gain = gain;
    line.offset = offset;
  });
</script>

<Sheet title={t.planView.line} {onclose}>
  <div class="fields">
    {#if filters.length || line.filter}
      <div class="group">
        <span class="label muted">{s.row.filter}</span>
        <SegmentedControl
          label={s.row.filter}
          options={[
            ...filters.map((name) => ({ value: name, label: name })),
            ...(line.filter && !filters.includes(line.filter) ? [{ value: line.filter, label: line.filter }] : []),
            { value: NONE, label: s.row.none },
          ]}
          value={line.filter ?? NONE}
          onchange={(value) => (line.filter = value === NONE ? null : value)} />
      </div>
    {/if}
    <NumberField label={s.row.exposure} bind:value={exposure} min={0.001} max={7200} unit="s" />
    <Stepper label={s.row.count} bind:value={count} min={1} max={10000} />
    {#if line.done}<p class="muted small">{t.planView.lineDone(line.done)}</p>{/if}
    <NumberField label={s.row.gain} bind:value={gain} min={0} max={10000} hint={s.row.settingHint(now(camera?.gain))} />
    <NumberField label={s.row.offset} bind:value={offset} min={0} max={10000} hint={s.row.settingHint(now(camera?.offset))} />
  </div>
  {#snippet actions()}
    <ConfirmButton label={s.row.remove} confirmLabel={s.row.removeConfirm} onconfirm={onremove} />
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
