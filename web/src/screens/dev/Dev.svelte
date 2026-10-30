<script lang="ts">
  // Troubleshooting screen inherited from the dev shell: every INDI property,
  // driver messages, and a bare exposure control. English only and temporary:
  // stages 2.7–2.10 replace it with real screens.
  import Icon from "../../components/Icon.svelte";
  import { cancelJob, expose, loop } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href } from "../../lib/router.svelte";
  import type { IndiDevice, IndiProperty, JobInfo } from "../../lib/types";
  import Property from "./Property.svelte";

  const indi = $derived(live.app.indi);
  const devices = $derived(Object.entries(indi?.devices ?? {}).sort(([a], [b]) => a.localeCompare(b)));
  const messages = $derived((indi?.messages ?? []).slice(-5).reverse());

  const camera = $derived(live.app.cameras?.main_camera);
  const jobs = $derived((live.app.jobs ?? {}) as Record<string, JobInfo>);
  const cameraJob = $derived(
    Object.entries(jobs).find(([, j]) => j.state === "running" && j.resources.includes("main_camera")),
  );
  let exposure = $state(1);
  let error = $state("");

  async function act(action: () => Promise<unknown>): Promise<void> {
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, i18n.t);
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

<div class="dev">
  <a class="back" href={href({ screen: "rig" })}><Icon name="chevronLeft" />{i18n.t.tabs.rig}</a>
  <h1 class="title">INDI properties</h1>

  {#if camera}
    <section class="device box">
      <div class="row">
        <span class="device-name">Main camera</span>
        <span class="muted">{camera.device}</span>
        <label class="muted">exposure (s) <input type="number" min="0" step="0.1" bind:value={exposure} /></label>
        {#if cameraJob}
          <button type="button" onclick={() => act(() => cancelJob(cameraJob[0]))}>Stop {cameraJob[1].kind}</button>
          <span class="muted">{cameraJob[1].message ?? ""}</span>
        {:else}
          <button type="button" onclick={() => act(() => expose("main_camera", exposure))}>Expose</button>
          <button type="button" onclick={() => act(() => loop("main_camera", exposure))}>Loop</button>
        {/if}
      </div>
      {#if error}<p class="error">{error}</p>{/if}
      {#if camera.preview}
        <p class="muted mono">
          {camera.preview.stars} stars · HFR {camera.preview.hfr ?? "–"} px · {camera.preview.width}×{camera.preview.height}
          · {camera.preview.exposure} s {camera.preview.frame_type} · worker {camera.preview.seconds} s
        </p>
        <img class="preview" src={camera.preview.url} alt="Latest preview" />
      {/if}
    </section>
  {/if}

  {#if devices.length === 0}
    <p class="muted">No INDI devices yet. Is indiserver running?</p>
  {/if}
  {#each devices as [name, device] (name)}
    <details class="device">
      <summary>
        <span class="device-name">{name}</span>
        <span class="muted">{isConnected(device) ? "connected" : "disconnected"}</span>
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
</div>

<style>
  .dev {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: var(--space-4) 0 var(--space-8);
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-height: var(--touch);
    align-self: flex-start;
    text-decoration: none;
  }
  .dev :global(button),
  .dev :global(input),
  .dev :global(select) {
    min-height: 44px;
    padding: 0 12px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--raised);
  }
  .dev :global(button) {
    cursor: pointer;
  }
  .device {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 4px 16px;
  }
  .box {
    padding: 12px 16px;
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
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .preview {
    display: block;
    max-width: 100%;
    margin-top: 8px;
    border-radius: 10px;
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
