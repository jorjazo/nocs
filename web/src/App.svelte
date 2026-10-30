<script lang="ts">
  import {
    cancelJob,
    connectProfile,
    disconnectEquipment,
    expose,
    getAuth,
    loop,
    pair,
    revokeDevice,
    setObserver,
    setUp,
  } from "./lib/api";
  import { live } from "./lib/live.svelte";
  import Property from "./lib/Property.svelte";
  import type {
    AuthStatus,
    CameraState,
    EquipmentState,
    IndiDevice,
    IndiProperty,
    IndiState,
    JobInfo,
  } from "./lib/types";

  // Authentication (ADR 0014): set up or pair first; the real screens come in stage 2.6.
  let auth = $state<AuthStatus | null>(null);
  let authError = $state("");
  let passphrase = $state("");
  let deviceName = $state("Dev shell");

  async function refreshAuth(): Promise<void> {
    try {
      auth = await getAuth();
    } catch (e) {
      authError = errorText(e);
    }
  }
  void refreshAuth();

  $effect(() => {
    if (auth?.role) live.start();
    else live.stop();
  });
  // A closed socket may mean this device was revoked: ask where it stands.
  $effect(() => {
    if (live.status === "closed") void refreshAuth();
  });

  async function submitAuth(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await authAction(() => (auth?.setup_required ? setUp : pair)(passphrase, deviceName));
    if (!authError) passphrase = "";
  }

  async function authAction(action: () => Promise<unknown>): Promise<void> {
    authError = "";
    try {
      await action();
    } catch (e) {
      authError = errorText(e);
    }
    await refreshAuth();
  }

  function errorText(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }

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

  const camera = $derived(
    (live.state.cameras as Record<string, CameraState> | undefined)?.main_camera,
  );
  const jobs = $derived((live.state.jobs ?? {}) as unknown as Record<string, JobInfo>);
  const cameraJob = $derived(
    Object.entries(jobs).find(([, j]) => j.state === "running" && j.resources.includes("main_camera")),
  );
  let exposure = $state(1);

  async function equipmentAction(action: () => Promise<unknown>): Promise<void> {
    equipmentError = "";
    try {
      await action();
    } catch (e) {
      equipmentError = errorText(e);
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
    {#if auth?.role === "owner" && auth.device}
      {@const device = auth.device}
      {@const observer = auth.observer}
      <button type="button" aria-pressed={observer} onclick={() => authAction(() => setObserver(!observer))}>
        Observers
      </button>
      <button type="button" onclick={() => authAction(() => revokeDevice(device.id))}>Unpair {device.name}</button>
    {:else if auth?.role === "observer"}
      <span class="chip">observer</span>
    {/if}
    <button type="button" aria-pressed={night} onclick={() => (night = !night)}>Night</button>
  </div>
</header>

<main>
  {#if auth && auth.role !== "owner"}
    <form class="device equipment" onsubmit={submitAuth}>
      <div class="row">
        <span class="device-name">{auth.setup_required ? "Set up the owner passphrase" : "Pair this device"}</span>
        <label class="muted">
          passphrase
          <input
            type="password"
            minlength="8"
            required
            autocomplete={auth.setup_required ? "new-password" : "current-password"}
            bind:value={passphrase} />
        </label>
        <label class="muted">device <input required maxlength="64" bind:value={deviceName} /></label>
        <button type="submit">{auth.setup_required ? "Set up" : "Pair"}</button>
      </div>
      {#if authError}<p class="error">{authError}</p>{/if}
    </form>
  {:else if authError}
    <p class="error">{authError}</p>
  {/if}

  {#if auth?.role}
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

    {#if camera}
      <section class="device equipment">
        <div class="row">
          <span class="device-name">Main camera</span>
          <span class="muted">{camera.device}</span>
          <label class="muted">exposure (s) <input type="number" min="0" step="0.1" bind:value={exposure} /></label>
          {#if cameraJob}
            <button type="button" onclick={() => equipmentAction(() => cancelJob(cameraJob[0]))}>
              Stop {cameraJob[1].kind}
            </button>
            <span class="muted">{cameraJob[1].message ?? ""}</span>
          {:else}
            <button type="button" onclick={() => equipmentAction(() => expose("main_camera", exposure))}>Expose</button>
            <button type="button" onclick={() => equipmentAction(() => loop("main_camera", exposure))}>Loop</button>
          {/if}
        </div>
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
  .preview {
    display: block;
    max-width: 100%;
    margin-top: 8px;
    border-radius: 10px;
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
