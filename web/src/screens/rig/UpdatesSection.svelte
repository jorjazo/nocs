<script lang="ts">
  // Rig → Updates, where nocs-system installs them (ADR 0025): NOCS first, then
  // INDI and PHD2, then the system as counts; every package behind a disclosure.
  // For the owner only: observers can do nothing with them.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Section from "../../components/Section.svelte";
  import { ApiError, reboot, runUpdate } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDateTime, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { installedCount, isToday, summarize } from "../../lib/updates";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const system = $derived(live.app.system ?? null);
  const can = (op: string) => auth.owner && (system?.operations.includes(op) ?? false);

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

  // Closed, the header says whether there is anything to install.
  const headline = $derived.by(() => {
    if (!updates) return null;
    if (updates.state === "installing") return t.system.installing;
    if (!updates.checked) return t.system.notChecked;
    return summary.total > 0 ? t.system.available(summary.total) : t.system.upToDate;
  });
  // The same updates that light the Rig tab (rigsections.updatesWorthIt) say why here.
  const status = $derived.by((): { tone: "accent" | "warning"; text: string } | null => {
    if (updates?.reboot_required) return { tone: "warning", text: t.system.needsRestart };
    if (summary.nocs) return { tone: "accent", text: t.system.newVersion };
    if (summary.system.security > 0) return { tone: "warning", text: t.system.security };
    return null;
  });

  type Action = "check" | "install" | "rollback" | "restart";
  let busy = $state<Action | null>(null);
  let error = $state("");
  // Refused because something runs: offer to force it.
  let refused = $state<Action | null>(null);
  let restarting = $state(false);

  async function act(action: Action, run: () => Promise<void>): Promise<boolean> {
    busy = action;
    error = "";
    refused = null;
    try {
      await run();
      return true;
    } catch (e) {
      error = errorText(e, t);
      if (e instanceof ApiError && e.status === 409) refused = action;
      return false;
    } finally {
      busy = null;
    }
  }

  async function update(task: "check" | "install" | "rollback", force = false): Promise<void> {
    await act(task, () => runUpdate(task, force));
  }

  async function restart(force = false): Promise<void> {
    if (await act("restart", () => reboot(force))) restarting = true;
  }
</script>

{#if updates && auth.owner}
  {@const canInstall = summary.total > 0 && updates.state !== "installing" && updates.state !== "checking"}
  <Section id="updates" title={t.system.updates} summary={headline} {status}>
    {#if updates.state === "checking"}
      <p class="caption muted" role="status">{t.system.checking}</p>
    {:else if checkedText}
      <p class="caption muted">{checkedText}</p>
    {/if}
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
      {#if updates.error}<p class="error">{updates.error}</p>{/if}
    {:else if updates.state === "failed"}
      <p class="error">{t.system.installFailed} {updates.error ?? ""}</p>
    {:else if updates.error}
      <p class="error">{updates.error}</p>
    {/if}
    {#if updates.reboot_required}
      <Banner icon="alert" tone="warning">{t.system.rebootRequired}</Banner>
      {#if can("power.reboot") && updates.state !== "installing"}
        <div class="buttons">
          {#if refused === "restart"}
            <ConfirmButton label={t.system.restartAnyway} confirmLabel={t.system.confirmRestart} onconfirm={() => restart(true)} />
          {:else}
            <ConfirmButton
              label={t.system.restart}
              confirmLabel={t.system.confirmRestart}
              busy={busy === "restart"}
              onconfirm={() => restart()} />
          {/if}
        </div>
      {/if}
      {#if restarting}<p class="muted" role="status">{t.system.restarting}</p>{/if}
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
    {#if error}<p class="error">{error}</p>{/if}

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
  </Section>
{/if}

<style>
  .buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
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
</style>
