<script lang="ts">
  // Rig's "This computer": its health for everyone; for the owner, its name on
  // the network, restart, shut down and the diagnostics bundle (ADR 0027).
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
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
  } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { hostName } from "../lib/boxsetup";
  import { errorText } from "../lib/errors";
  import {
    formatBytes,
    formatDateTime,
    formatDecimal,
    formatPlain,
    formatTemperature,
    formatTime,
  } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { installedCount, isToday, summarize } from "../lib/updates";

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

  // -- Actions --------------------------------------------------------------------

  type Action = "rename" | "restart" | "shutDown" | "indiserver" | "phd2" | "check" | "install" | "rollback";
  let busy = $state<Action | null>(null);
  let error = $state("");
  // A restart or shut down refused because something runs: offer to force it.
  let refused = $state<Action | null>(null);
  let done = $state<"restarting" | "shuttingDown" | "restartedIndi" | "restartedPhd2" | null>(
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
    const wanted = hostName(name);
    if (wanted === null) {
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

  // -- Updates (ADR 0025): NOCS, then INDI and PHD2, then the system as counts ------

  const updates = $derived(live.app.updates ?? null);
  const summary = $derived(summarize(updates?.packages ?? []));
  const installedSummary = $derived(summarize(updates?.upgraded ?? []));
  const checkedText = $derived.by(() => {
    const checked = updates?.checked;
    if (!checked) return null;
    return t.system.checkedAt(isToday(checked) ? formatTime(checked, locale) : formatDateTime(checked, locale));
  });
  const names = (kinds: { kind: "indi" | "phd2" }[]) =>
    new Intl.ListFormat(locale, { type: "conjunction" }).format(kinds.map((c) => t.system.component[c.kind]));
  // The server refuses to install while a job runs (it would end it): say so first.
  const jobRunning = $derived(Object.values(live.app.jobs ?? {}).some((job) => job.state === "running"));

  async function update(task: "check" | "install" | "rollback", force = false): Promise<void> {
    await act(task, () => runUpdate(task, force));
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
        {@const canInstall = summary.total > 0 && updates.state !== "installing" && updates.state !== "checking"}
        <div class="updates">
          <div class="updates-head">
            <h3 class="label muted">{t.system.updates}</h3>
            {#if updates.state === "checking"}
              <span class="caption muted" role="status">{t.system.checking}</span>
            {:else if checkedText}
              <span class="caption muted">{checkedText}</span>
            {/if}
          </div>
          {#if !updates.checked && updates.state !== "checking"}
            <p class="muted">{t.system.neverChecked}</p>
          {/if}

          <ul class="components">
            <li class="component">
              <span class="what">{t.system.nocs}</span>
              <span class="detail">
                <span class="versions mono">
                  {#if summary.nocs}
                    {summary.nocs.from} → {summary.nocs.to}
                  {:else}
                    {updates.installed ?? "—"}
                  {/if}
                </span>
                {#if summary.nocs}
                  <Chip tone="accent">{t.system.newVersion}</Chip>
                {:else if updates.checked && updates.installed}
                  <Chip tone="ok">{t.system.upToDate}</Chip>
                {/if}
              </span>
            </li>
            {#if updates.checked}
              {#each summary.components as component (component.kind)}
                <li class="component">
                  <span class="what">{t.system.component[component.kind]}</span>
                  <span class="detail">
                    <span class="versions mono">{component.from} → {component.to}</span>
                    {#if component.count > 1}<span class="caption muted">{t.system.packages(component.count)}</span>{/if}
                  </span>
                </li>
              {:else}
                <li class="component">
                  <span class="what">{t.system.rigUpToDate}</span>
                  <span class="detail"><Chip tone="ok">{t.system.upToDate}</Chip></span>
                </li>
              {/each}
              <li class="component">
                <span class="what">{t.system.system}</span>
                <span class="detail">
                  {#if summary.system.count}
                    <span>{t.system.systemUpdates(summary.system.count, summary.system.security)}</span>
                  {:else}
                    <Chip tone="ok">{t.system.upToDate}</Chip>
                  {/if}
                </span>
              </li>
            {/if}
          </ul>

          {#if summary.total > 0}
            <details class="packages">
              <summary>{t.system.showPackages(summary.total)}</summary>
              {#each summary.groups as group (group.kind)}
                <h4 class="label muted">{t.system.group[group.kind]}</h4>
                <ul class="package-list">
                  <!-- By index: apt lists a name once per architecture on a multiarch PC. -->
                  {#each group.packages as pkg, i (i)}
                    <li>
                      <span class="package-name mono">{pkg.name}</span>
                      {#if pkg.security}<span class="security caption">{t.system.security}</span>{/if}
                      <span class="package-versions caption muted mono">{pkg.from} → {pkg.to}</span>
                    </li>
                  {/each}
                </ul>
              {/each}
            </details>
          {/if}

          {#if updates.state === "installing"}
            <p role="status">{t.system.installing}</p>
          {:else if updates.state === "succeeded"}
            <p class="muted">
              {t.system.installed(updates.task === "install" ? installedCount(updates.upgraded, updates.packages) : 0)}
              {#if installedSummary.components.length && !updates.reboot_required}
                {t.system.restartRig(names(installedSummary.components))}
              {/if}
            </p>
          {:else if updates.state === "failed"}
            <p class="error">{t.system.installFailed} {updates.error ?? ""}</p>
          {:else if updates.error}
            <p class="error">{updates.error}</p>
          {/if}
          {#if updates.reboot_required}
            <Banner icon="alert" tone="warning">{t.system.rebootRequired}</Banner>
            {#if can("power.reboot") && updates.state !== "installing"}
              <div class="buttons">
                <ConfirmButton
                  label={t.system.restart}
                  confirmLabel={t.system.confirmRestart}
                  busy={busy === "restart"}
                  onconfirm={() => restart()} />
              </div>
            {/if}
          {/if}
          {#if updates.log.length && updates.state !== "idle"}
            <pre class="log">{updates.log.slice(-8).join("\n")}</pre>
          {/if}

          {#if canInstall}
            <div class="effects caption">
              <span class="label muted">{t.system.effectsTitle}</span>
              <ul>
                <li>{summary.nocs ? t.system.effectNocs : t.system.effectNoNocs}</li>
                {#if summary.components.length}<li>{t.system.effectRig(names(summary.components))}</li>{/if}
                {#if summary.reboot}<li>{t.system.effectKernel}</li>{/if}
                <li>{t.system.effectNight}</li>
              </ul>
            </div>
            {#if jobRunning}<Banner icon="alert" tone="warning">{t.system.running}</Banner>{/if}
          {/if}

          <div class="buttons">
            <Button
              busy={busy === "check" || updates.state === "checking"}
              disabled={updates.state === "installing"}
              onclick={() => update("check")}>{t.system.check}</Button>
            {#if canInstall}
              {#if refused === "install"}
                <ConfirmButton label={t.system.installAnyway} confirmLabel={t.system.confirmInstall} onconfirm={() => update("install", true)} />
              {:else}
                <ConfirmButton
                  label={t.system.install(summary.total)}
                  confirmLabel={summary.nocs ? t.system.confirmInstallNocs : t.system.confirmInstall}
                  busy={busy === "install"}
                  onconfirm={() => update("install")} />
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
  .updates-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .updates h3,
  .packages h4 {
    margin: 0;
  }
  .packages h4:not(:first-of-type) {
    margin-top: var(--space-2);
  }
  .components,
  .package-list,
  .effects ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .components {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .component {
    display: grid;
    grid-template-columns: 72px minmax(0, 1fr);
    align-items: baseline;
    gap: var(--space-3);
  }
  .what {
    font-weight: 600;
  }
  .detail {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    min-height: 28px;
  }
  .versions {
    overflow-wrap: anywhere;
  }
  .packages summary {
    display: list-item;
    padding: 10px 0;
    color: var(--accent);
    font-weight: 600;
    cursor: pointer;
  }
  .packages[open] {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-bottom: var(--space-2);
  }
  .package-list li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-2);
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--line);
  }
  .package-name {
    font-size: 15px;
    overflow-wrap: anywhere;
  }
  .package-versions {
    flex-basis: 100%;
    overflow-wrap: anywhere;
  }
  .security {
    color: var(--warning);
    font-weight: 600;
  }
  .effects {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .effects li {
    position: relative;
    padding-left: var(--space-3);
  }
  .effects li::before {
    content: "·";
    position: absolute;
    left: 2px;
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
