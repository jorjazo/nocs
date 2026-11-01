<script lang="ts">
  // What sits in each slot of the wheel connected now (ADR 0016): names are
  // kept per physical wheel, so its label tells the user's wheels apart. A slot
  // can be sent into place to check by eye which filter it holds.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import Button from "../../components/Button.svelte";
  import Icon from "../../components/Icon.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import TextField from "../../components/TextField.svelte";
  import { selectFilter, setFilterNames } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { COMMON_FILTERS, holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";

  let { onclose }: { onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const wheel = $derived(live.app.filter_wheel ?? null);
  const lockedBy = $derived(holder(live.app.jobs, "filter_wheel"));
  const locked = $derived(lockedBy !== null && lockedBy.info.kind !== "filter");
  const disabled = $derived(!auth.owner || locked);

  // Drafts, from the wheel when the sheet opened.
  const initial = untrack(() => live.app.filter_wheel);
  let label = $state(initial?.label ?? "");
  let names = $state<string[]>(initial ? [...initial.names] : []);
  let active = $state(0);
  const inputs: HTMLInputElement[] = [];

  const duplicate = $derived.by(() => {
    const seen = new Set<string>();
    for (const name of names) {
      const key = name.trim().toLocaleLowerCase();
      if (key && seen.has(key)) return name.trim();
      seen.add(key);
    }
    return null;
  });

  let busy = $state(false);
  let error = $state("");

  async function run(action: () => Promise<unknown>, close = false): Promise<void> {
    busy = true;
    error = "";
    try {
      await action();
      if (close) onclose();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  // A common name fills the slot being edited and moves on to the next one.
  function pick(name: string): void {
    names[active] = name;
    if (active < names.length - 1) {
      active += 1;
      inputs[active]?.focus({ preventScroll: true });
    }
  }

  $effect(() => {
    if (!wheel) onclose();
  });
</script>

<Sheet title={t.wheel.title} {onclose}>
  {#if wheel}
    {#if !wheel.confirmed && wheel.key}<Banner icon="filter" tone="warning">{t.wheel.isNew}</Banner>{/if}
    <TextField label={t.wheel.label} hint={t.wheel.labelHint} bind:value={label} maxlength={80} />
    <p class="caption muted">
      {wheel.device} · {wheel.key ? t.wheel.identity(wheel.key) : t.wheel.identifying}
    </p>

    <fieldset class="slots" {disabled}>
      <legend class="label muted">{t.wheel.slots}</legend>
      <p class="caption muted">{t.wheel.slotsHint}</p>
      <div class="common" role="group" aria-label={t.wheel.common}>
        {#each COMMON_FILTERS as name (name)}
          <button type="button" class="chip" onclick={() => pick(name)}>{name}</button>
        {/each}
        <button type="button" class="chip" onclick={() => pick("")}>{t.wheel.empty}</button>
      </div>
      <ol>
        {#each names as _, i (i)}
          <li class:active={i === active}>
            <span class="number mono" aria-hidden="true">{i + 1}</span>
            <input
              bind:this={inputs[i]}
              bind:value={names[i]}
              aria-label={t.wheel.slot(i + 1)}
              placeholder={t.wheel.empty}
              maxlength={32}
              autocomplete="off"
              spellcheck={false}
              onfocus={() => (active = i)} />
            {#if wheel.slot === i + 1}
              <span class="current caption">{t.wheel.current}</span>
            {/if}
            <button
              type="button"
              class="move"
              aria-label={t.wheel.moveHere(i + 1)}
              disabled={wheel.moving || wheel.slot === i + 1}
              onclick={() => void run(() => selectFilter({ slot: i + 1 }))}>
              <Icon name="filter" size={20} />
            </button>
          </li>
        {/each}
      </ol>
    </fieldset>

    {#if locked && auth.owner}<p class="caption muted">{t.wheel.locked}</p>{/if}
    {#if duplicate}<p class="caption error">{t.wheel.duplicate(duplicate)}</p>{/if}
    <SequenceHold resources={["filter_wheel"]} />
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {/if}

  {#snippet actions()}
    <Button
      variant="primary"
      {busy}
      disabled={disabled || !wheel?.key || duplicate !== null}
      onclick={() => void run(() => setFilterNames({ filters: names.map((name) => name.trim()), label: label.trim() }), true)}>
      {t.wheel.save}
    </Button>
  {/snippet}
</Sheet>

<style>
  .slots {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
  ol {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding-left: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--bg);
  }
  li.active {
    border-color: var(--accent);
  }
  .number {
    width: 1.5em;
    color: var(--muted);
  }
  input {
    flex: 1;
    min-width: 0;
    min-height: var(--touch);
    border: 0;
    background: transparent;
    font-size: 17px;
    outline: none;
  }
  .current {
    color: var(--accent);
    white-space: nowrap;
  }
  .move {
    display: grid;
    place-items: center;
    flex: none;
    width: var(--touch);
    height: var(--touch);
    border: 0;
    background: transparent;
    color: var(--accent);
    cursor: pointer;
  }
  .move:disabled {
    color: var(--muted);
    cursor: default;
  }
  .common {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .chip {
    min-width: var(--touch);
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-full);
    background: var(--raised);
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
  }
  .error {
    color: var(--error);
  }
</style>
