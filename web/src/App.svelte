<script lang="ts">
  import { live } from "./lib/live.svelte";
  import Property from "./lib/Property.svelte";
  import type { IndiDevice, IndiProperty, IndiState } from "./lib/types";

  let night = $state(false);
  $effect(() => {
    document.documentElement.dataset.theme = night ? "night" : "dusk";
  });

  const indi = $derived((live.state.indi ?? {}) as IndiState);
  const devices = $derived(Object.entries(indi.devices ?? {}).sort(([a], [b]) => a.localeCompare(b)));
  const messages = $derived((indi.messages ?? []).slice(-5).reverse());

  function groups(device: IndiDevice): [string, [string, IndiProperty][]][] {
    const byGroup = new Map<string, [string, IndiProperty][]>();
    for (const entry of Object.entries(device.properties)) {
      const group = entry[1].group || "General";
      byGroup.set(group, [...(byGroup.get(group) ?? []), entry]);
    }
    return [...byGroup];
  }

  function isConnected(device: IndiDevice): boolean {
    return device.properties.CONNECTION?.elements.CONNECT?.value === true;
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
        <span class="muted count">{Object.keys(device.properties).length} properties</span>
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
  .messages ul {
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
    font-size: 13px;
  }
</style>
