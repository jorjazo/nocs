<script lang="ts">
  // Rig's "This computer": its health for everyone; for the owner, its name on
  // the network, restart, shut down and the diagnostics bundle (ADR 0027).
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import TextField from "../components/TextField.svelte";
  import {
    ApiError,
    DIAGNOSTICS_URL,
    powerOff,
    reboot,
    restartService,
    runUpdate,
    setHostname,
    useGpsSite,
  } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { formatBytes, formatDecimal, formatPlain, formatTemperature, formatTime } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const system = $derived(live.app.system ?? null);
  const health = $derived(system?.health ?? null);
  const timeSource = $derived(live.app.clock?.source ?? null);
  // Only where gpsd runs (the appliance, ADR 0029).
  const gps = $derived(live.app.gps?.connected ? live.app.gps : null);
  const gpsPosition = $derived.by(() => {
    if (!gps || gps.latitude === null || gps.longitude === null) return null;
    const parts = [`${formatDecimal(gps.latitude, locale, 4)}°`, `${formatDecimal(gps.longitude, locale, 4)}°`];
    if (gps.elevation !== null) parts.push(t.system.gpsElevation(formatPlain(gps.elevation, locale)));
    return parts.join(" · ");
  });
  const can = (op: string) => auth.owner && (system?.operations.includes(op) ?? false);

  const readouts = $derived.by(() => {
    if (!health) return [];
    const items: { label: string; value: string; low?: boolean }[] = [];
    if (health.cpu_temperature !== null) {
      items.push({ label: t.system.temperature, value: formatTemperature(health.cpu_temperature, locale, 0) });
    }
    if (health.fan !== null) items.push({ label: t.system.fan, value: t.system.rpm(formatPlain(health.fan, locale)) });
    if (health.memory_used !== null) items.push({ label: t.system.memory, value: `${health.memory_used} %` });
    if (health.disk_free !== null) {
      items.push({ label: t.system.disk, value: t.system.free(formatBytes(health.disk_free, locale)) });
    }
    if (timeSource) items.push({ label: t.system.time, value: t.system.timeSource[timeSource] });
    if (gps) items.push({ label: t.system.gps, value: gpsPosition ?? t.system.gpsNoFix });
    if (health.under_voltage !== null) {
      const low = health.under_voltage;
      items.push({ label: t.system.supply, value: low ? t.system.supplyLow : t.system.supplyOk, low });
    }
    return items;
  });

  // -- Name -----------------------------------------------------------------------

  let renaming = $state(false);
  let name = $state("");
  let nameError = $state("");
  let renamed = $state<string | null>(null);
  // One DNS label, as nocs-system checks it: the box is also <name>.local.
  const HOSTNAME = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

  // -- Actions --------------------------------------------------------------------

  type Action = "rename" | "restart" | "shutDown" | "gps" | "indiserver" | "phd2" | "check" | "install" | "rollback";
  let busy = $state<Action | null>(null);
  let error = $state("");
  // A restart or shut down refused because something runs: offer to force it.
  let refused = $state<Action | null>(null);
  let done = $state<"restarting" | "shuttingDown" | "gpsUsed" | "restartedIndi" | "restartedPhd2" | null>(
    null,
  );

  async function act(action: Action, run: () => Promise<void>): Promise<boolean> {
    busy = action;
    error = "";
    nameError = "";
    refused = null;
    done = null;
    try {
      await run();
      return true;
    } catch (e) {
      if (action === "rename") nameError = errorText(e, t);
      else error = errorText(e, t);
      if (e instanceof ApiError && e.status === 409) refused = action;
      return false;
    } finally {
      busy = null;
    }
  }

  async function rename(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const wanted = name.trim().toLowerCase();
    if (!HOSTNAME.test(wanted)) {
      nameError = t.system.nameInvalid;
      return;
    }
    if (await act("rename", () => setHostname(wanted))) {
      renaming = false;
      renamed = wanted;
    }
  }

  async function restart(force = false): Promise<void> {
    if (await act("restart", () => reboot(force))) done = "restarting";
  }

  async function restartEngine(service: "indiserver" | "phd2", force = false): Promise<void> {
    if (await act(service, () => restartService(service, force))) {
      done = service === "indiserver" ? "restartedIndi" : "restartedPhd2";
    }
  }

  const updates = $derived(live.app.updates ?? null);

  async function update(task: "check" | "install" | "rollback", force = false): Promise<void> {
    await act(task, () => runUpdate(task, force));
  }

  async function useGps(): Promise<void> {
    if (await act("gps", async () => void (await useGpsSite()))) done = "gpsUsed";
  }

  async function shutDown(force = false): Promise<void> {
    if (await act("shutDown", () => powerOff(force))) done = "shuttingDown";
  }
</script>

{#if system}
  <section class="system" aria-labelledby="system-title">
    <h2 class="heading" id="system-title">{t.system.title}</h2>

    {#each health?.warnings ?? [] as warning (warning)}
      <Banner icon="alert" tone={warning === "under_voltage" ? "error" : "warning"}>{t.system.warnings[warning]}</Banner>
    {/each}
    {#if health?.under_voltage === false && health.under_voltage_seen}
      <p class="muted">{t.system.underVoltageSeen(formatTime(health.under_voltage_seen, locale))}</p>
    {/if}

    {#if readouts.length > 0}
      <dl class="readouts">
        {#each readouts as item (item.label)}
          <div class="readout-item">
            <dt class="label muted">{item.label}</dt>
            <dd class="mono" class:low={item.low}>{item.value}</dd>
          </div>
        {/each}
      </dl>
    {/if}

    {#if gps?.site_differs && auth.owner}
      <div class="gps">
        <span class="muted">{t.system.gpsUseHint}</span>
        <Button busy={busy === "gps"} onclick={useGps}>{t.system.gpsUse}</Button>
      </div>
    {/if}

    <div class="name">
      <span class="label muted">{t.system.name}</span>
      {#if renaming}
        <form class="rename" onsubmit={rename}>
          <TextField
            label={t.system.rename}
            hint={t.system.renameHint}
            error={nameError || undefined}
            bind:value={name}
            required
            maxlength={63} />
          <div class="buttons">
            <Button variant="primary" type="submit" busy={busy === "rename"}>{t.system.save}</Button>
            <Button
              variant="text"
              onclick={() => {
                renaming = false;
                nameError = "";
              }}>{t.system.cancel}</Button>
          </div>
        </form>
      {:else}
        <div class="line">
          <span class="mono">{system.hostname}.local</span>
          {#if can("hostname.set")}
            <Button
              variant="text"
              onclick={() => {
                name = system.hostname;
                renaming = true;
              }}>{t.system.rename}</Button>
          {/if}
        </div>
      {/if}
      {#if renamed}<p class="muted">{t.system.renamed(renamed)}</p>{/if}
    </div>

    {#if auth.owner}
      {#if can("power.reboot") || can("power.poweroff")}
        <div class="buttons">
          {#if can("power.reboot")}
            <ConfirmButton
              label={t.system.restart}
              confirmLabel={t.system.confirmRestart}
              busy={busy === "restart"}
              onconfirm={() => restart()} />
          {/if}
          {#if can("power.poweroff")}
            <ConfirmButton
              label={t.system.shutDown}
              confirmLabel={t.system.confirmShutDown}
              busy={busy === "shutDown"}
              onconfirm={() => shutDown()} />
          {/if}
        </div>
      {:else}
        <p class="muted">{t.system.noPower}</p>
      {/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if can("services.restart")}
        <div class="buttons">
          <ConfirmButton
            label={t.system.restartIndi}
            confirmLabel={t.system.confirmRestartIndi}
            busy={busy === "indiserver"}
            onconfirm={() => restartEngine("indiserver")} />
          <ConfirmButton
            label={t.system.restartPhd2}
            confirmLabel={t.system.confirmRestartPhd2}
            busy={busy === "phd2"}
            onconfirm={() => restartEngine("phd2")} />
        </div>
      {/if}
      {#if refused === "indiserver" || refused === "phd2"}
        {@const service = refused}
        <ConfirmButton
          label={service === "indiserver" ? t.system.restartIndiAnyway : t.system.restartPhd2Anyway}
          confirmLabel={service === "indiserver" ? t.system.confirmRestartIndi : t.system.confirmRestartPhd2}
          onconfirm={() => restartEngine(service, true)} />
      {:else if refused === "restart"}
        <ConfirmButton label={t.system.restartAnyway} confirmLabel={t.system.confirmRestart} onconfirm={() => restart(true)} />
      {:else if refused === "shutDown"}
        <ConfirmButton label={t.system.shutDownAnyway} confirmLabel={t.system.confirmShutDown} onconfirm={() => shutDown(true)} />
      {/if}
      {#if done}<p class="muted" role="status">{t.system[done]}</p>{/if}

      {#if updates}
        <div class="updates">
          <h3 class="label muted">{t.system.updates}</h3>
          <p>
            {#if updates.installed}<span class="mono">{t.system.version(updates.installed)}</span> ·{/if}
            {#if updates.state === "checking"}
              {t.system.checking}
            {:else if updates.checked}
              {updates.packages.length ? t.system.available(updates.packages.length) : t.system.upToDate}
              <span class="muted">({t.system.checkedAt(formatTime(updates.checked, locale))})</span>
            {:else}
              <span class="muted">{t.system.neverChecked}</span>
            {/if}
          </p>
          {#if updates.packages.length && updates.state !== "installing"}
            <p class="caption muted mono">
              {updates.packages.map((p) => `${p.name} ${p.to}`).join(" · ")}
            </p>
          {/if}
          {#if updates.state === "installing"}
            <p role="status">{t.system.installing}</p>
          {:else if updates.state === "succeeded"}
            <p class="muted">{t.system.installed}</p>
          {:else if updates.state === "failed"}
            <p class="error">{t.system.installFailed} {updates.error ?? ""}</p>
          {:else if updates.error}
            <p class="error">{updates.error}</p>
          {/if}
          {#if updates.log.length && updates.state !== "idle"}
            <pre class="log">{updates.log.slice(-8).join("\n")}</pre>
          {/if}
          <div class="buttons">
            <Button
              busy={busy === "check" || updates.state === "checking"}
              disabled={updates.state === "installing"}
              onclick={() => update("check")}>{t.system.check}</Button>
            {#if updates.packages.length && updates.state !== "installing"}
              {#if refused === "install"}
                <ConfirmButton label={t.system.installAnyway} confirmLabel={t.system.confirmInstall} onconfirm={() => update("install", true)} />
              {:else}
                <ConfirmButton label={t.system.install} confirmLabel={t.system.confirmInstall} busy={busy === "install"} onconfirm={() => update("install")} />
              {/if}
            {/if}
            {#if updates.previous && updates.previous !== updates.installed && updates.state !== "installing"}
              {@const previous = updates.previous}
              <ConfirmButton
                label={t.system.rollback(previous)}
                confirmLabel={t.system.confirmRollback}
                busy={busy === "rollback"}
                onconfirm={() => update("rollback", refused === "rollback")} />
            {/if}
          </div>
        </div>
      {/if}

      <div class="diagnostics">
        <a href={DIAGNOSTICS_URL} download>{t.system.diagnostics}</a>
        <span class="caption muted">{t.system.diagnosticsHint}</span>
      </div>
    {/if}
  </section>
{/if}

<style>
  .system {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .readouts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: var(--space-3) var(--space-4);
    margin: 0;
  }
  .readout-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  dd {
    margin: 0;
    font-size: 17px;
    line-height: 24px;
  }
  .low {
    color: var(--error);
  }
  .gps {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .name {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
    font-size: 17px;
  }
  .rename {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
  .updates {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .log {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-button);
    background: var(--raised);
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .diagnostics {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-top: var(--space-2);
  }
  .diagnostics a {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
</style>
