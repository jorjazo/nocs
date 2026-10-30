<script lang="ts">
  import { connectProfile, disconnectEquipment } from "./lib/api";
  import { live } from "./lib/live.svelte";
  import Property from "./lib/Property.svelte";
  import type { EquipmentState, IndiDevice, IndiProperty, IndiState } from "./lib/types";

  let night = $state(false);
  $effect(() => {
    document.documentElement.dataset.theme = night ? "night" : "dusk";
  });

  const indi = $derived((live.state.indi ?? {}) as IndiState);
  const devices = $derived(Object.entries(indi.devices ?? {}).sort(([a], [b]) => a.localeCompare(b)));
  const messages = $derived((indi.messages ?? []).slice(-5).reverse());

  const equipment = $derived(live.state.equipment as EquipmentState | undefined);
  const profiles = $derived(Object.entries(equipment?.profiles ?? {}));
  let selected = $state("");
  let equipmentError = $state("");
  $effect(() => {
    if (!selected) selected = equipment?.active ?? profiles[0]?.[0] ?? "";
  });

  async function equipmentAction(action: () => Promise<void>): Promise<void> {
    equipmentError = "";
    try {
      await action();
    } catch (e) {
      equipmentError = e instanceof Error ? e.message : String(e);
    }
  }

  function groups(device: IndiDevice): [string, [string, IndiProperty][]][] {
    const byGroup = new Map<string, [string, IndiProperty][]>();
    for (const entry of Object.entries(device.properties ?? {})) {
      const group = entry[1].group || "General";
      byGroup.set(group, [...(byGroup.get(group) ?? []), entry]);
    }
    return [...byGroup];
  }

  function isConnected(device: IndiDevice): boolean {
    return device.properties?.CONNECTION?.elements.CONNECT?.value === true;
  }
</script>

<header>
  <div class="brand">
    <strong>NOCS</strong>
    <span class="muted">dev shell</span>
  </div>
  <div class="status">
    <span class="chip" class:good={live.status === "open"}>server: {live.status}</span>
    <span class="chip" class:good={indi.server?.connected === true} title={indi.server?.error ?? ""}>
      indi {indi.server ? `${indi.server.host}:${indi.server.port}` : ""}: {indi.server?.connected
        ? "connected"
        : "offline"}
    </span>
    <button type="button" aria-pressed={night} onclick={() => (night = !night)}>Night</button>
  </div>
</header>

<main>
  {#if equipment}
    <section class="device equipment">
      <div class="row">
        <span class="device-name">Equipment</span>
        {#if profiles.length === 0}
          <span class="muted">No profiles yet (PUT /api/profiles/&lt;id&gt;).</span>
        {:else}
          <select bind:value={selected} disabled={equipment.connection !== "disconnected"}>
            {#each profiles as [id, profile] (id)}
              <option value={id}>{profile.name}</option>
            {/each}
          </select>
          <button type="button" disabled={!selected} onclick={() => equipmentAction(() => connectProfile(selected))}>
            {equipment.connection === "disconnected" ? "Connect" : "Retry"}
          </button>
          <button
            type="button"
            disabled={equipment.connection === "disconnected"}
            onclick={() => equipmentAction(disconnectEquipment)}>Disconnect</button>
        {/if}
        <span class="chip" class:good={equipment.connection === "connected"}>{equipment.connection}</span>
      </div>
      {#if equipment.error || equipmentError}
        <p class="error">{equipmentError || equipment.error}</p>
      {/if}
      <ul class="roles">
        {#each Object.entries(equipment.devices) as [role, device] (role)}
          <li>
            <span class="mono">{role}</span>
            <span class="muted">{device.device ?? device.driver}</span>
            <span class="chip" class:good={device.status === "ready"}>{device.status}</span>
            {#if device.error}<span class="error">{device.error}</span>{/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if devices.length === 0}
    <p class="muted">No INDI devices yet. Is indiserver running?</p>
  {/if}
  {#each devices as [name, device] (name)}
    <details class="device">
      <summary>
        <span class="device-name">{name}</span>
        <span class="chip" class:good={isConnected(device)}>
          {isConnected(device) ? "connected" : "disconnected"}
        </span>
        <span class="muted count">
          {[...(device.interfaces ?? []), `${Object.keys(device.properties ?? {}).length} properties`].join(" · ")}
        </span>
      </summary>
      {#each groups(device) as [group, properties] (group)}
        <section>
          <h3>{group}</h3>
          {#each properties as [propName, prop] (propName)}
            <Property device={name} name={propName} {prop} />
          {/each}
        </section>
      {/each}
    </details>
  {/each}

  {#if messages.length}
    <section class="messages">
      <h3>Driver messages</h3>
      <ul>
        {#each messages as message, i (i)}
          <li><span class="mono muted">{message.timestamp ?? ""}</span> {message.device ?? ""}: {message.text}</li>
        {/each}
      </ul>
    </section>
  {/if}
</main>

<style>
  header {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--line);
  }
  .brand {
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .brand strong {
    letter-spacing: 0.08em;
  }
  .status {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--raised);
    color: var(--muted);
    font-size: 13px;
  }
  .chip.good {
    color: var(--ok);
  }
  main {
    max-width: 960px;
    margin: 0 auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .device {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 4px 16px;
  }
  summary {
    min-height: 52px;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    cursor: pointer;
  }
  .device-name {
    font-weight: 600;
  }
  .count {
    font-size: 13px;
  }
  h3 {
    margin: 16px 0 0;
    font-size: 13px;
    font-weight: 500;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .equipment {
    padding: 12px 16px;
  }
  .row,
  .roles li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .roles {
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
  }
  .error {
    color: var(--error);
    margin: 8px 0 0;
  }
  .messages ul {
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
    font-size: 13px;
  }
</style>
