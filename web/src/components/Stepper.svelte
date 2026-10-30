<script lang="ts">
  import { formatPlain, parseNumber } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import Icon from "./Icon.svelte";

  // A number typed or nudged with − and +. `value` is null while the text is
  // not a number within range, so the caller can refuse to apply it.
  let {
    label,
    value = $bindable(),
    min,
    max,
    step = 1,
    unit,
    hint,
    disabled = false,
  }: {
    label: string;
    value: number | null;
    min: number;
    max: number;
    step?: number;
    unit?: string;
    hint?: string;
    disabled?: boolean;
  } = $props();

  const id = $props.id();
  const t = $derived(i18n.t);
  let text = $state(value === null ? "" : formatPlain(value, i18n.locale));
  const parsed = $derived(parseNumber(text));
  const error = $derived(
    parsed === null ? t.live.invalid : parsed < min || parsed > max ? t.live.outOfRange(fmt(min), fmt(max)) : "",
  );

  function fmt(number: number): string {
    return formatPlain(number, i18n.locale);
  }

  $effect(() => {
    value = error ? null : parsed;
  });

  function nudge(direction: 1 | -1): void {
    const base = parsed ?? min;
    // Snap to the step grid, then stay within range.
    const next = Math.round((base + direction * step) / step) * step;
    text = fmt(Math.min(max, Math.max(min, Number(next.toFixed(6)))));
  }
</script>

<div class="field">
  <label class="label" for={id}>{label}</label>
  <div class="control" class:invalid={!!error}>
    <button type="button" class="nudge" aria-label={t.live.decrease(label)} {disabled} onclick={() => nudge(-1)}>
      <Icon name="minus" />
    </button>
    <input
      {id}
      type="text"
      inputmode="decimal"
      autocomplete="off"
      bind:value={text}
      {disabled}
      aria-invalid={error ? true : undefined}
      aria-describedby="{id}-note" />
    {#if unit}<span class="unit" aria-hidden="true">{unit}</span>{/if}
    <button type="button" class="nudge" aria-label={t.live.increase(label)} {disabled} onclick={() => nudge(1)}>
      <Icon name="plus" />
    </button>
  </div>
  <p class="note" class:error={!!error} id="{id}-note">{error || hint || t.live.range(fmt(min), fmt(max))}</p>
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .label {
    color: var(--muted);
    font-size: 15px;
    font-weight: 500;
  }
  .control {
    display: flex;
    align-items: center;
    min-height: var(--primary-height);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--bg);
  }
  .control:focus-within {
    border-color: var(--accent);
  }
  .control.invalid {
    border-color: var(--error);
  }
  input {
    flex: 1;
    min-width: 0;
    min-height: var(--primary-height);
    padding: 0 var(--space-2);
    border: 0;
    background: transparent;
    font-family: var(--font-mono);
    font-size: 20px;
    text-align: center;
    outline: none;
  }
  .unit {
    color: var(--muted);
    font-family: var(--font-mono);
  }
  .nudge {
    display: grid;
    place-items: center;
    flex: none;
    width: var(--primary-height);
    height: var(--primary-height);
    border: 0;
    background: transparent;
    color: var(--accent);
    cursor: pointer;
  }
  .nudge:disabled {
    color: var(--muted);
    cursor: default;
  }
  .note {
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
  }
  .note.error {
    color: var(--error);
  }
</style>
