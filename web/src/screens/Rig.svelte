<script lang="ts">
  // Rig: the active profile, its trains and devices, connect / disconnect,
  // where frames are saved, who has access, and this screen's preferences.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import DeviceRow from "../components/DeviceRow.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import Icon from "../components/Icon.svelte";
  import ScreenHeader from "../components/ScreenHeader.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import Toggle from "../components/Toggle.svelte";
  import {
    connectProfile,
    disconnectEquipment,
    getProfile,
    listDevices,
    revokeDevice,
    setObserver,
  } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { slotLabel } from "../lib/camera.svelte";
  import { connectionTone, ROLE_ICONS, ROLES, roles, roleTone } from "../lib/equipment";
  import { errorText } from "../lib/errors";
  import { formatBytes, formatDateTime, formatDecimal, formatPlain, formatTemperature } from "../lib/format";
  import { i18n, LANGUAGE_NAMES } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { formatDec, formatRa, mountActivity } from "../lib/mount.svelte";
  import { LOCALES, prefs, THEMES } from "../lib/prefs.svelte";
  import { href, router } from "../lib/router.svelte";
  import FilterWheelSheet from "./devices/FilterWheelSheet.svelte";
  import FocuserSheet from "./devices/FocuserSheet.svelte";
  import MountSheet from "./devices/MountSheet.svelte";
  import PowerSheet from "./devices/PowerSheet.svelte";
  import StorageDrives from "./StorageDrives.svelte";
  import SystemSection from "./SystemSection.svelte";
  import type { CameraState, Optics, PairedDevice, Profile, Role, RoleState } from "../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const equipment = $derived(live.app.equipment);
  const cameras = $derived(live.app.cameras);
  const server = $derived(live.app.indi?.server ?? null);
  const storage = $derived(live.app.storage);

  // -- Profile and connection ---------------------------------------------------

  const profiles = $derived(
    Object.entries(equipment?.profiles ?? {}).sort(([, a], [, b]) => a.name.localeCompare(b.name)),
  );
  let picked = $state<string | null>(null);
  const profileId = $derived(
    picked !== null && equipment?.profiles[picked] ? picked : (equipment?.active ?? profiles[0]?.[0] ?? null),
  );
  const connection = $derived(equipment?.connection ?? "disconnected");
  // Until a profile is connected the state lists no roles: show the selected
  // profile's devices instead, all offline.
  const roleList = $derived.by((): [Role, RoleState][] => {
    const current = equipment ? roles(equipment) : [];
    if (current.length > 0 || !profile) return current;
    return ROLES.flatMap((role): [Role, RoleState][] => {
      const config = profile?.devices?.[role];
      if (!config) return [];
      return [[role, { driver: config.driver, device: config.device ?? null, status: "disconnected", error: null }]];
    });
  });
  const devicesByRole = $derived(Object.fromEntries(roleList) as Partial<Record<Role, RoleState>>);
  const anyError = $derived(roleList.some(([, device]) => device.status === "error"));

  let busy = $state<"connect" | "disconnect" | null>(null);
  let actionError = $state("");

  async function run(kind: "connect" | "disconnect", action: () => Promise<void>): Promise<void> {
    busy = kind;
    actionError = "";
    try {
      await action();
    } catch (e) {
      actionError = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  // The optics are in the profile, which only the owner may read.
  let profile = $state<Profile | null>(null);
  $effect(() => {
    const id = profileId;
    const owner = auth.owner;
    profile = null;
    if (id === null || !owner) return;
    let current = true;
    getProfile(id)
      .then((loaded) => {
        if (current) profile = loaded;
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  });

  // -- Trains -------------------------------------------------------------------

  function deviceName(device: RoleState | undefined): string | null {
    return device ? (device.device ?? device.driver) : null;
  }

  function train(optics: Optics | null | undefined, camera: CameraState | undefined, parts: (string | null)[]) {
    if (!optics) return null;
    const focal = optics.focal_length * (optics.reducer ?? 1);
    const ratio = optics.aperture ? focal / optics.aperture : null;
    const lens = `${formatDecimal(focal, locale, 0)} mm${ratio ? ` f/${formatDecimal(ratio, locale, 1)}` : ""}`;
    const sensor = camera?.sensor;
    const known = sensor && sensor.width > 0 && sensor.pixel_size > 0;
    const scale = known ? `${formatDecimal((206.265 * sensor.pixel_size) / focal, locale, 2)}″/px` : null;
    const fov = known
      ? [sensor.width, sensor.height]
          .map((px) => formatDecimal((((px * sensor.pixel_size) / 1000 / focal) * 180) / Math.PI, locale, 1) + "°")
          .join(" × ")
      : null;
    return { chain: [lens, ...parts.filter((part) => part !== null)], scale, fov };
  }

  const imaging = $derived(
    train(profile?.imaging, cameras?.main_camera, [
      deviceName(devicesByRole.filter_wheel),
      deviceName(devicesByRole.focuser),
      deviceName(devicesByRole.main_camera),
    ]),
  );
  const guiding = $derived(
    train(
      profile?.guiding_through_imaging ? profile.imaging : profile?.guiding,
      cameras?.guide_camera,
      [deviceName(devicesByRole.guide_camera)],
    ),
  );

  const power = $derived(live.app.power ?? null);
  const weather = $derived(live.app.weather ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const wheel = $derived(live.app.filter_wheel ?? null);
  const mount = $derived(live.app.mount ?? null);
  let sheet = $state<"power" | "focuser" | "filter_wheel" | "mount" | null>(null);

  function subtitle(role: Role): string {
    const parts = [t.roles[role]];
    const camera = role === "main_camera" || role === "guide_camera" ? cameras?.[role] : undefined;
    if (camera?.temperature != null) parts.push(`${formatDecimal(camera.temperature, locale, 1)}\u00a0°C`);
    if (role === "power" && power?.input) {
      const { voltage, current } = power.input;
      if (voltage !== null) parts.push(`${formatDecimal(voltage, locale, 1)}\u00a0V`);
      if (current !== null) parts.push(`${formatDecimal(current, locale, 2)}\u00a0A`);
    }
    if (role === "weather" && weather) {
      if (weather.temperature !== null) parts.push(`${formatDecimal(weather.temperature, locale, 1)}\u00a0°C`);
      if (weather.humidity !== null) parts.push(`${formatDecimal(weather.humidity, locale, 0)}\u00a0%`);
    }
    if (role === "focuser" && focuser) {
      parts.push(t.rig.position(formatPlain(focuser.position, locale)));
      if (focuser.temperature !== null) parts.push(formatTemperature(focuser.temperature, locale));
    }
    if (role === "mount" && mount) {
      parts.push(`${formatRa(mount.ra_j2000)} ${formatDec(mount.dec_j2000)}`, mountActivity(mount, t).text);
    }
    if (role === "filter_wheel" && wheel) {
      if (wheel.label) parts.push(wheel.label);
      if (wheel.slot) parts.push(slotLabel(wheel, wheel.slot, t));
      if (!wheel.confirmed && wheel.key) parts.push(t.rig.wheelNew);
    }
    return parts.join(" · ");
  }

  function moving(role: Role): boolean {
    return (
      (role === "focuser" && !!focuser?.moving) ||
      (role === "filter_wheel" && !!wheel?.moving) ||
      (role === "mount" && !!mount && mountActivity(mount, t).moving)
    );
  }

  function opener(role: Role): (() => void) | undefined {
    if (role === "focuser" && focuser) return () => (sheet = "focuser");
    if (role === "filter_wheel" && wheel) return () => (sheet = "filter_wheel");
    if (role === "power" && power) return () => (sheet = "power");
    if (role === "mount" && mount) return () => (sheet = "mount");
    return undefined;
  }

  // -- Storage ------------------------------------------------------------------

  const destination = $derived(storage?.destinations.find((d) => d.id === storage.destination) ?? null);
  const destinationDetails = $derived.by(() => {
    if (!destination || !storage) return "";
    const parts = [
      destination.sd ? t.rig.storageSd : destination.internal ? t.rig.storageInternal : null,
      destination.system && !destination.internal ? t.rig.storageSystem : null,
      destination.fs,
      storage.choice === "auto" ? t.rig.storageAuto : null,
      destination.writable ? null : t.rig.storageReadOnly,
    ];
    return parts.filter((part) => part !== null).join(" · ");
  });
  const used = $derived(destination && destination.total > 0 ? 1 - destination.free / destination.total : 0);

  // -- Access -------------------------------------------------------------------

  let devices = $state<PairedDevice[] | null>(null);
  let accessError = $state("");
  let accessBusy = $state<string | null>(null);

  async function loadDevices(): Promise<void> {
    try {
      devices = await listDevices();
    } catch (e) {
      accessError = errorText(e, t);
    }
  }
  $effect(() => {
    if (auth.owner) void loadDevices();
  });
  const others = $derived((devices ?? []).filter((device) => !device.current));

  async function access(key: string, action: () => Promise<void>): Promise<void> {
    accessBusy = key;
    accessError = "";
    try {
      await action();
    } catch (e) {
      accessError = errorText(e, t);
    } finally {
      accessBusy = null;
    }
  }
</script>

<ScreenHeader title={t.rig.title}>
  {#snippet trailing()}
    {#if profiles.length > 0 && profileId !== null}
      <label class="picker">
        <span class="visually-hidden">{t.rig.profile}</span>
        <select
          value={profileId}
          disabled={!auth.owner || connection !== "disconnected"}
          onchange={(event) => (picked = event.currentTarget.value)}>
          {#each profiles as [id, summary] (id)}
            <option value={id}>{summary.name}</option>
          {/each}
        </select>
        <Icon name="chevronDown" size={20} />
      </label>
    {/if}
  {/snippet}
</ScreenHeader>

{#if !live.synced}
  <p class="loading muted" role="status">{t.boot.loading}</p>
{:else if equipment && profiles.length === 0}
  <EmptyState icon="rig" title={t.rig.noProfiles} body={t.rig.noProfilesBody}>
    {#snippet action()}
      {#if auth.owner}
        <Button variant="primary" onclick={() => router.go({ screen: "profile", id: null })}>{t.rig.newProfile}</Button>
      {/if}
    {/snippet}
  </EmptyState>
{:else if equipment}
  <div class="sections">
    <section class="card equipment" aria-labelledby="equipment-title">
      <div class="line">
        <h2 class="heading" id="equipment-title">{t.rig.equipment}</h2>
        <Chip tone={equipment.error ? "error" : connectionTone(connection)}>{t.connection[connection]}</Chip>
      </div>
      {#if equipment.error || actionError}
        <p class="error">{actionError || equipment.error}</p>
      {/if}
      {#if auth.owner && profileId !== null}
        {@const id = profileId}
        <div class="buttons">
          {#if connection === "disconnected"}
            <Button variant="primary" wide busy={busy === "connect"} onclick={() => run("connect", () => connectProfile(id))}>
              {t.rig.connect}
            </Button>
          {:else}
            {#if anyError}
              <Button variant="primary" busy={busy === "connect"} onclick={() => run("connect", () => connectProfile(id))}>
                {t.rig.retry}
              </Button>
            {/if}
            <Button
              busy={busy === "disconnect"}
              disabled={connection === "disconnecting"}
              onclick={() => run("disconnect", disconnectEquipment)}>
              {t.rig.disconnect}
            </Button>
          {/if}
        </div>
        <div class="links">
          <a href={href({ screen: "profile", id })}>{t.rig.editProfile}</a>
          <a href={href({ screen: "profile", id: null })}>{t.rig.newProfile}</a>
        </div>
      {/if}
    </section>

    {#if imaging || guiding}
      <section class="card trains">
        {#each [{ label: t.rig.imagingTrain, value: imaging }, { label: t.rig.guidingTrain, value: guiding }] as item (item.label)}
          {#if item.value}
            <div class="train">
              <div class="line">
                <h2 class="label muted">{item.label}</h2>
                <span class="mono muted">{[item.value.fov, item.value.scale].filter(Boolean).join(" · ")}</span>
              </div>
              <p class="chain">
                {#each item.value.chain as part, i (i)}
                  {#if i > 0}<span class="arrow" aria-hidden="true">→</span>{/if}
                  <span class:muted={i === 0}>{part}</span>
                {/each}
              </p>
            </div>
          {/if}
        {/each}
      </section>
    {/if}

    <section aria-labelledby="devices-title">
      <div class="line section-title">
        <h2 class="heading" id="devices-title">{t.rig.devices}</h2>
        {#if auth.owner && profileId !== null}
          <a href={href({ screen: "profile", id: profileId })}>{t.rig.addDevice}</a>
        {/if}
      </div>
      {#if roleList.length === 0}
        <p class="muted">{t.rig.noDevices}</p>
      {:else}
        <ul class="rows">
          {#each roleList as [role, device] (role)}
            <DeviceRow
              icon={ROLE_ICONS[role]}
              title={device.device ?? t.roles[role]}
              subtitle={device.device ? subtitle(role) : device.driver}
              error={device.error}
              onclick={opener(role)}>
              {#snippet trailing()}
                {#if moving(role)}
                  <Chip tone="accent">{t.rig.moving}</Chip>
                {:else}
                  <Chip tone={roleTone(device.status, connection)}>{t.deviceStatus[device.status]}</Chip>
                {/if}
              {/snippet}
            </DeviceRow>
          {/each}
          {#if server}
            <DeviceRow icon="server" title={t.rig.indiServer} subtitle="{server.host}:{server.port}" error={server.error}>
              {#snippet trailing()}
                {#if server.connected && !server.responsive}
                  <Chip tone="warning">{t.rig.indiNotAnswering}</Chip>
                {:else}
                  <Chip tone={server.connected ? "ok" : "error"}>
                    {server.connected ? t.rig.indiConnected : t.rig.indiOffline}
                  </Chip>
                {/if}
              {/snippet}
            </DeviceRow>
          {/if}
        </ul>
      {/if}
    </section>

    {#if storage}
      <section aria-labelledby="storage-title">
        <h2 class="heading section-title" id="storage-title">{t.rig.storage}</h2>
        <ul class="rows">
          {#if destination}
            <DeviceRow icon="storage" title={destination.label} subtitle={destinationDetails} error={storage.error}>
              {#snippet trailing()}
                <span class="mono free">{formatBytes(destination.free, locale)}</span>
              {/snippet}
            </DeviceRow>
          {:else}
            <DeviceRow icon="storage" title={t.rig.storageNone} error={storage.error}>
              {#snippet trailing()}<Chip tone="error">{t.deviceStatus.error}</Chip>{/snippet}
            </DeviceRow>
          {/if}
        </ul>
        {#if destination}
          <div class="meter-row">
            <div
              class="meter"
              role="meter"
              aria-label={t.rig.storage}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(used * 100)}>
              <span style:width="{Math.round(used * 100)}%"></span>
            </div>
            <span class="caption muted">
              {t.rig.storageFree(formatBytes(destination.free, locale), formatBytes(destination.total, locale))}
            </span>
          </div>
        {/if}
        <StorageDrives />
      </section>
    {/if}

    <SystemSection />

    <section aria-labelledby="access-title">
      <h2 class="heading section-title" id="access-title">{t.access.title}</h2>
      {#if auth.owner && auth.status?.device}
        {@const me = auth.status.device}
        <ul class="rows">
          <DeviceRow icon="device" title={me.name} subtitle="{t.access.thisDevice} · {t.access.pairedSince(formatDateTime(me.created, locale))}">
            {#snippet trailing()}
              <ConfirmButton
                label={t.access.unpair}
                confirmLabel={t.access.confirmUnpair}
                busy={accessBusy === "me"}
                onconfirm={() => access("me", () => auth.unpair())} />
            {/snippet}
          </DeviceRow>
        </ul>
        <div class="toggle-row">
          <Toggle
            label={t.access.observers}
            hint={t.access.observersHint}
            checked={auth.status.observer}
            disabled={accessBusy === "observer"}
            onchange={(enabled) =>
              access("observer", async () => {
                await setObserver(enabled);
                await auth.refresh();
              })} />
        </div>
        <h3 class="label muted subsection">{t.access.devices}</h3>
        {#if devices && others.length === 0}
          <p class="muted">{t.access.noDevices}</p>
        {:else}
          <ul class="rows">
            {#each others as device (device.id)}
              <DeviceRow icon="device" title={device.name} subtitle={t.access.lastUsed(formatDateTime(device.last_used, locale))}>
                {#snippet trailing()}
                  <ConfirmButton
                    label={t.access.revoke}
                    confirmLabel={t.access.confirmRevoke}
                    busy={accessBusy === device.id}
                    onconfirm={() =>
                      access(device.id, async () => {
                        await revokeDevice(device.id);
                        await loadDevices();
                      })} />
                {/snippet}
              </DeviceRow>
            {/each}
          </ul>
        {/if}
        {#if accessError}<p class="error">{accessError}</p>{/if}
      {:else}
        <div class="observer">
          <p class="muted">{t.access.observerNote}</p>
          <Button onclick={() => (auth.wantsPair = true)}>{t.link.pair}</Button>
        </div>
      {/if}
    </section>

    <section aria-labelledby="prefs-title">
      <h2 class="heading section-title" id="prefs-title">{t.prefs.title}</h2>
      <div class="prefs">
        <div class="pref">
          <span class="label muted">{t.language.label}</span>
          <SegmentedControl
            label={t.language.label}
            options={LOCALES.map((value) => ({ value, label: LANGUAGE_NAMES[value] }))}
            value={prefs.locale}
            onchange={(value) => prefs.setLocale(value)} />
        </div>
        <div class="pref">
          <span class="label muted">{t.theme.label}</span>
          <SegmentedControl
            label={t.theme.label}
            options={THEMES.map((value) => ({ value, label: t.theme[value] }))}
            value={prefs.theme}
            onchange={(value) => prefs.setTheme(value)} />
        </div>
      </div>
    </section>

    <a class="advanced" href={href({ screen: "dev" })}>
      <span class="text">
        <span>{t.rig.advanced}</span>
        <span class="caption muted">{t.rig.advancedHint}</span>
      </span>
      <Icon name="chevronRight" />
    </a>
  </div>
{:else}
  <Banner icon="alert" tone="warning">{t.boot.loading}</Banner>
{/if}

{#if sheet === "power"}
  <PowerSheet onclose={() => (sheet = null)} />
{:else if sheet === "focuser"}
  <FocuserSheet onclose={() => (sheet = null)} />
{:else if sheet === "mount"}
  <MountSheet onclose={() => (sheet = null)} />
{:else if sheet === "filter_wheel"}
  <FilterWheelSheet onclose={() => (sheet = null)} />
{/if}

<style>
  .loading {
    padding: var(--space-8) 0;
  }
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--space-8);
    padding-bottom: var(--space-8);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
    margin-top: var(--space-1);
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
  .links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-6);
  }
  .links a,
  .line a {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  .trains {
    gap: 0;
  }
  .train {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) 0;
  }
  .train + .train {
    border-top: 1px solid var(--line);
  }
  .chain {
    display: flex;
    flex-wrap: wrap;
    column-gap: var(--space-2);
    font-size: 17px;
    line-height: 26px;
    overflow-wrap: anywhere;
  }
  .arrow {
    color: var(--muted);
  }
  .section-title {
    margin-bottom: var(--space-2);
  }
  .subsection {
    margin: var(--space-4) 0 0;
  }
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .free {
    color: var(--text);
  }
  .meter-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-3);
  }
  .meter {
    height: 8px;
    border-radius: var(--radius-full);
    background: var(--raised);
    overflow: hidden;
  }
  .meter span {
    display: block;
    height: 100%;
    background: var(--accent);
    border-radius: inherit;
  }
  .toggle-row {
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--line);
  }
  .observer {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
  }
  .prefs {
    display: grid;
    gap: var(--space-4);
  }
  @media (min-width: 768px) {
    .prefs {
      grid-template-columns: 1fr 1fr;
    }
  }
  .pref {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .picker {
    position: relative;
    display: inline-flex;
    align-items: center;
    color: var(--text);
  }
  .picker select {
    appearance: none;
    min-height: 48px;
    max-width: 60vw;
    padding: 0 44px 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    font-weight: 500;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .picker select:disabled {
    cursor: default;
  }
  .picker :global(.icon) {
    position: absolute;
    right: 14px;
    pointer-events: none;
  }
  .advanced {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    min-height: 64px;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-card);
    border: 1px solid var(--line);
    color: var(--text);
    text-decoration: none;
  }
  .advanced .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
</style>
