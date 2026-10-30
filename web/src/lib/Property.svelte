<script lang="ts">
  import { setIndiProperty } from "./api";
  import { formatNumber } from "./format";
  import StateDot from "./StateDot.svelte";
  import type { IndiElement, IndiProperty } from "./types";

  let { device, name, prop }: { device: string; name: string; prop: IndiProperty } = $props();

  let error = $state<string | null>(null);
  let drafts = $state<Record<string, string>>({});

  const writable = $derived(prop.perm !== "ro");
  const elements = $derived(Object.entries(prop.elements));

  async function send(values: Record<string, string | number | boolean>): Promise<void> {
    error = null;
    try {
      await setIndiProperty(device, name, values);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  function pressSwitch(element: string): void {
    const on = prop.elements[element]?.value === true;
    if (prop.rule === "AnyOfMany") {
      void send({ [element]: !on });
      return;
    }
    const turnOn = prop.rule === "OneOfMany" || !on;
    const values: Record<string, boolean> = {};
    for (const [key] of elements) values[key] = key === element && turnOn;
    void send(values);
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    const values: Record<string, string | number> = {};
    for (const [key, element] of elements) {
      const draft = drafts[key] ?? display(element);
      values[key] = prop.type === "number" ? Number(draft) : draft;
    }
    drafts = {};
    void send(values);
  }

  function display(element: IndiElement): string {
    const value = element.value;
    if (typeof value === "number") return formatNumber(value, "format" in element ? element.format : undefined);
    if (typeof value === "object") return `${value.format || "—"} · ${value.size} bytes`;
    return String(value);
  }
</script>

<div class="property">
  <div class="head">
    <StateDot state={prop.state} />
    <span class="label">{prop.label}</span>
    <span class="name mono muted">{name}</span>
  </div>

  {#if prop.type === "switch"}
    <div class="switches">
      {#each elements as [key, element] (key)}
        <button
          type="button"
          class:on={element.value === true}
          aria-pressed={element.value === true}
          disabled={!writable}
          onclick={() => pressSwitch(key)}>{element.label}</button
        >
      {/each}
    </div>
  {:else if (prop.type === "number" || prop.type === "text") && writable}
    <form class="fields" onsubmit={submit}>
      {#each elements as [key, element] (key)}
        <label>
          <span class="muted">{element.label}</span>
          <span class="mono current">{display(element)}</span>
          <input
            class="mono"
            value={drafts[key] ?? (prop.type === "number" ? String(element.value) : display(element))}
            oninput={(e) => (drafts[key] = e.currentTarget.value)}
          />
        </label>
      {/each}
      <button type="submit">Set</button>
    </form>
  {:else}
    <dl class="values">
      {#each elements as [key, element] (key)}
        <dt class="muted">{element.label}</dt>
        <dd class="mono">
          {#if prop.type === "light"}
            <StateDot state={element.value as IndiProperty["state"]} />
          {/if}
          {display(element)}
        </dd>
      {/each}
    </dl>
  {/if}

  {#if error}<p class="error" role="alert">{error}</p>{/if}
</div>

<style>
  .property {
    padding: 12px 0;
    border-bottom: 1px solid var(--line);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .label {
    font-weight: 500;
  }
  .name {
    font-size: 12px;
  }
  .switches {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .switches .on {
    background: var(--accent);
    color: var(--on-accent);
    border-color: var(--accent);
    font-weight: 600;
  }
  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 8px;
    align-items: end;
  }
  .fields label {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
  }
  .fields .current {
    font-size: 15px;
  }
  .fields input {
    width: 100%;
  }
  .values {
    display: grid;
    grid-template-columns: minmax(120px, max-content) 1fr;
    gap: 2px 16px;
    margin: 0;
    font-size: 13px;
  }
  .values dd {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .error {
    margin: 0;
    color: var(--error);
    font-size: 13px;
  }
</style>
