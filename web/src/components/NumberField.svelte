<script lang="ts">
  import { formatPlain, parseNumber } from "../lib/format";
  import { i18n } from "../lib/i18n";

  // A number typed by hand that may be left empty (null). `valid` is false
  // while the text is not a number within range, so the form can refuse to save.
  let {
    label,
    value = $bindable(),
    valid = $bindable(true),
    min,
    max,
    unit,
    hint,
    placeholder,
  }: {
    label: string;
    value: number | null;
    valid?: boolean;
    min: number;
    max: number;
    unit?: string;
    hint?: string;
    placeholder?: string;
  } = $props();

  const id = $props.id();
  const t = $derived(i18n.t);
  let text = $state(value === null ? "" : formatPlain(value, i18n.locale, 6));
  const parsed = $derived(parseNumber(text));
  const error = $derived(
    text.trim() === ""
      ? ""
      : parsed === null
        ? t.live.invalid
        : parsed < min || parsed > max
          ? t.live.outOfRange(formatPlain(min, i18n.locale), formatPlain(max, i18n.locale))
          : "",
  );

  $effect(() => {
    valid = !error;
    value = error ? null : parsed;
  });
</script>

<div class="field">
  <label class="label" for={id}>{label}</label>
  <div class="control" class:invalid={!!error}>
    <input
      {id}
      type="text"
      inputmode="decimal"
      autocomplete="off"
      {placeholder}
      bind:value={text}
      aria-invalid={error ? true : undefined}
      aria-describedby={error || hint ? `${id}-note` : undefined} />
    {#if unit}<span class="unit" aria-hidden="true">{unit}</span>{/if}
  </div>
  {#if error || hint}<p class="note" class:error={!!error} id="{id}-note">{error || hint}</p>{/if}
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
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
    padding-right: var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
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
    padding: 0 var(--space-4);
    border: 0;
    background: transparent;
    font-family: var(--font-mono);
    font-size: 17px;
    outline: none;
  }
  .unit {
    color: var(--muted);
    font-family: var(--font-mono);
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
