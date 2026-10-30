<script lang="ts">
  import type { FullAutoFill } from "svelte/elements";
  import { i18n } from "../lib/i18n";
  import Icon from "./Icon.svelte";

  let {
    label,
    hint,
    error,
    value = $bindable(""),
    type = "text",
    autocomplete,
    required = false,
    minlength,
    maxlength,
  }: {
    label: string;
    hint?: string;
    error?: string;
    value?: string;
    // Passwords get a button to show what was typed: one field, no typos.
    type?: "text" | "password";
    autocomplete?: FullAutoFill;
    required?: boolean;
    minlength?: number;
    maxlength?: number;
  } = $props();

  const id = $props.id();
  let revealed = $state(false);
  const inputType = $derived(type === "password" && !revealed ? "password" : "text");
  const describedBy = $derived([error ? `${id}-error` : "", hint ? `${id}-hint` : ""].join(" ").trim());
</script>

<div class="field">
  <label class="label" for={id}>{label}</label>
  <div class="control" class:invalid={!!error}>
    <input
      {id}
      type={inputType}
      bind:value
      {autocomplete}
      {required}
      {minlength}
      {maxlength}
      autocapitalize={type === "password" ? "off" : undefined}
      spellcheck={type === "password" ? false : undefined}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy || undefined} />
    {#if type === "password"}
      <button
        type="button"
        class="reveal"
        aria-label={revealed ? i18n.t.passphrase.hide : i18n.t.passphrase.show}
        aria-pressed={revealed}
        onclick={() => (revealed = !revealed)}>
        <Icon name={revealed ? "eyeOff" : "eye"} />
      </button>
    {/if}
  </div>
  {#if error}<p class="error" id="{id}-error">{error}</p>{/if}
  {#if hint}<p class="hint" id="{id}-hint">{hint}</p>{/if}
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
    font-size: 17px;
    outline: none;
  }
  .reveal {
    display: grid;
    place-items: center;
    width: var(--primary-height);
    height: var(--primary-height);
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  .hint {
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
  }
  .error {
    color: var(--error);
    font-size: 13px;
    line-height: 18px;
  }
</style>
