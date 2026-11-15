<script lang="ts">
  // Rig → Optics and devices → Devices: the profile's devices with their status,
  // a way back for those that dropped out (restart the driver, cut the power of the
  // output that feeds them; never the mount's, ADR 0030), and the services they go
  // through, INDI and PHD2, with their restarts (ADR 0027). Without a profile only
  // the services: a server that does not answer must still say so.
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import DeviceRow from "../../components/DeviceRow.svelte";
  import Section from "../../components/Section.svelte";
  import { ApiError, powerCycle, restartDriver, restartService } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { slotLabel } from "../../lib/camera.svelte";
  import { ROLE_ICONS, roleTone } from "../../lib/equipment";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain, formatTemperature, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa, mountActivity } from "../../lib/mount.svelte";
  import { href } from "../../lib/router.svelte";
  import { devicesAttention } from "../../lib/rigsections";
  import FilterWheelSheet from "../devices/FilterWheelSheet.svelte";
  import FocuserSheet from "../devices/FocuserSheet.svelte";
  import MountSheet from "../devices/MountSheet.svelte";
  import PowerSheet from "../devices/PowerSheet.svelte";
  import type { ConnectionName, DeviceStatusName, Role, RoleState } from "../../lib/types";

  let {
    roles,
    connection,
    profileId,
  }: { roles: [Role, RoleState][]; connection: ConnectionName; profileId: string | null } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const cameras = $derived(live.app.cameras);
  const server = $derived(live.app.indi?.server ?? null);
  const phd2 = $derived(live.app.guiding?.phd2 ?? null);
  const power = $derived(live.app.power ?? null);
  const weather = $derived(live.app.weather ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const wheel = $derived(live.app.filter_wheel ?? null);
  const mount = $derived(live.app.mount ?? null);
  // A serial port being looked for, connecting (ADR 0048).
  const detecting = $derived(live.app.equipment?.detecting ?? null);
  let sheet = $state<"power" | "focuser" | "filter_wheel" | "mount" | null>(null);

  const ready = $derived(roles.filter(([, device]) => device.status === "ready").length);
  const attention = $derived(devicesAttention(live.app.equipment, server));

  // -- Recovery -----------------------------------------------------------------

  const FAILING: readonly DeviceStatusName[] = ["error", "disconnected", "unresponsive"];
  const failing = $derived(
    connection === "connected" && auth.owner ? roles.filter(([, device]) => FAILING.includes(device.status)) : [],
  );
  function fed(role: Role): boolean {
    return role !== "mount" && (power?.outputs.some((output) => output.feeds.includes(role)) ?? false);
  }

  type Busy = `restart:${Role}` | `cycle:${Role}` | "indiserver" | "phd2";
  let busy = $state<Busy | null>(null);
  let error = $state("");
  // A service restart refused because something runs: offer to force it.
  let refused = $state<"indiserver" | "phd2" | null>(null);
  let done = $state<"restartedIndi" | "restartedPhd2" | null>(null);

  async function run(kind: Busy, action: () => Promise<void>): Promise<boolean> {
    busy = kind;
    error = "";
    refused = null;
    done = null;
    try {
      await action();
      return true;
    } catch (e) {
      error = errorText(e, t);
      if ((kind === "indiserver" || kind === "phd2") && e instanceof ApiError && e.status === 409) refused = kind;
      return false;
    } finally {
      busy = null;
    }
  }

  async function restartEngine(service: "indiserver" | "phd2", force = false): Promise<void> {
    if (await run(service, () => restartService(service, force))) {
      done = service === "indiserver" ? "restartedIndi" : "restartedPhd2";
    }
  }
  const canRestart = $derived(auth.owner && (live.app.system?.operations.includes("services.restart") ?? false));

  // -- Rows ---------------------------------------------------------------------

  function subtitle(role: Role): string {
    const parts = [t.roles[role]];
    const name = roles.find(([r]) => r === role)?.[1].device;
    if (detecting && name === detecting.device) parts.push(t.rig.lookingForPort(detecting.attempt, detecting.attempts));
    const camera = role === "main_camera" || role === "guide_camera" ? cameras?.[role] : undefined;
    if (camera?.temperature != null) parts.push(`${formatDecimal(camera.temperature, locale, 1)} °C`);
    if (role === "power" && power?.input) {
      const { voltage, current } = power.input;
      if (voltage !== null) parts.push(`${formatDecimal(voltage, locale, 1)} V`);
      if (current !== null) parts.push(`${formatDecimal(current, locale, 2)} A`);
    }
    if (role === "weather" && weather) {
      if (weather.temperature !== null) parts.push(`${formatDecimal(weather.temperature, locale, 1)} °C`);
      if (weather.humidity !== null) parts.push(`${formatDecimal(weather.humidity, locale, 0)} %`);
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
</script>

<Section
  id="devices"
  title={t.rig.devices}
  summary={profileId === null ? null : roles.length > 0 ? t.rig.online(ready, roles.length) : t.rig.noDevices}
  status={attention ? { tone: attention === "problem" ? "error" : "warning", text: t.rig.attention[attention] } : null}>
  {#if profileId === null}
    <!-- No profile yet: Rig's empty state offers one; only the services below. -->
  {:else if roles.length === 0}
    <p class="muted">{t.rig.noDevices}</p>
  {:else}
    <ul class="rows">
      {#each roles as [role, device] (role)}
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
      {#each failing as [role, device] (role)}
        <li class="recover">
          <span>
            {device.unresponsive_since
              ? t.rig.notAnsweringSince(device.device ?? t.roles[role], formatTime(device.unresponsive_since, locale))
              : t.rig.recover(device.device ?? t.roles[role])}
          </span>
          <Button busy={busy === `restart:${role}`} onclick={() => run(`restart:${role}`, () => restartDriver(role))}>
            {t.rig.restartDriver}
          </Button>
          {#if fed(role)}
            <ConfirmButton
              label={t.rig.powerCycle}
              confirmLabel={t.rig.confirmPowerCycle}
              busy={busy === `cycle:${role}`}
              onconfirm={() => run(`cycle:${role}`, () => powerCycle(role))} />
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  {#if auth.owner && profileId !== null}
    <a class="add" href={href({ screen: "profile", id: profileId })}>{t.rig.addDevice}</a>
  {/if}

  {#if server || phd2}
    <h4 class="label muted subsection">{t.rig.services}</h4>
    <ul class="rows">
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
      {#if phd2}
        <DeviceRow
          icon="server"
          title="PHD2"
          subtitle={[`${phd2.host}:${phd2.port}`, phd2.version].filter(Boolean).join(" · ")}
          error={phd2.connected ? null : phd2.error}>
          {#snippet trailing()}
            <Chip tone={phd2.connected ? "ok" : "neutral"}>
              {phd2.connected ? t.rig.indiConnected : t.rig.indiOffline}
            </Chip>
          {/snippet}
        </DeviceRow>
      {/if}
    </ul>
    {#if canRestart}
      <div class="buttons">
        {#if refused === "indiserver"}
          <ConfirmButton
            label={t.system.restartIndiAnyway}
            confirmLabel={t.system.confirmRestartIndi}
            onconfirm={() => restartEngine("indiserver", true)} />
        {:else}
          <ConfirmButton
            label={t.system.restartIndi}
            confirmLabel={t.system.confirmRestartIndi}
            busy={busy === "indiserver"}
            onconfirm={() => restartEngine("indiserver")} />
        {/if}
        {#if refused === "phd2"}
          <ConfirmButton
            label={t.system.restartPhd2Anyway}
            confirmLabel={t.system.confirmRestartPhd2}
            onconfirm={() => restartEngine("phd2", true)} />
        {:else}
          <ConfirmButton
            label={t.system.restartPhd2}
            confirmLabel={t.system.confirmRestartPhd2}
            busy={busy === "phd2"}
            onconfirm={() => restartEngine("phd2")} />
        {/if}
      </div>
    {/if}
  {/if}
  {#if error}<p class="error">{error}</p>{/if}
  {#if done}<p class="muted" role="status">{t.system[done]}</p>{/if}
</Section>

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
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .recover {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) 0;
  }
  .recover span {
    flex: 1 1 12rem;
  }
  .add {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  .subsection {
    margin: var(--space-2) 0 0;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
</style>
