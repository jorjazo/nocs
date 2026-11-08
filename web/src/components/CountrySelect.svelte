<script lang="ts">
  // The country whose Wi-Fi channels the radio uses (ADR 0028): one of those the
  // kernel knows, by its name in the app's language.
  import { countryChoices } from "../lib/countries";
  import { i18n } from "../lib/i18n";

  let {
    label,
    hint,
    value = $bindable(""),
  }: {
    label: string;
    hint?: string;
    // A country code, or "" while none is chosen.
    value?: string;
  } = $props();

  const id = $props.id();
  const t = $derived(i18n.t);
  const choices = $derived(countryChoices(i18n.locale));
</script>

<label class="select">
  <span class="label muted">{label}</span>
  <select bind:value aria-describedby={hint ? `${id}-hint` : undefined}>
    <option value="" disabled>{t.wifi.chooseCountry}</option>
    {#each choices as choice (choice.code)}
      <option value={choice.code}>{choice.name}</option>
    {/each}
  </select>
  {#if hint}<span class="caption muted" id="{id}-hint">{hint}</span>{/if}
</label>

<style>
  .select {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .select .label {
    font-size: 15px;
  }
  select {
    min-height: var(--primary-height);
    width: 100%;
    padding: 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    text-overflow: ellipsis;
  }
</style>
