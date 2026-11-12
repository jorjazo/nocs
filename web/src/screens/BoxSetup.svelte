<script lang="ts">
  // The appliance's first run (ADR 0028), right after the owner pairs: in steps, the
  // access point's country and own password, maybe a home network, the box's name,
  // and a last look at what will happen. Nothing is sent before that last step: the
  // access point restarts (and this phone drops off it) only once its instructions
  // are on screen. Full screen, before anything else.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import CountrySelect from "../components/CountrySelect.svelte";
  import Icon from "../components/Icon.svelte";
  import TextField from "../components/TextField.svelte";
  import ThemeButton from "../components/ThemeButton.svelte";
  import Toggle from "../components/Toggle.svelte";
  import WifiPicker from "../components/WifiPicker.svelte";
  import { auth } from "../lib/auth.svelte";
  import { hostName, setupSteps, wifiPassword as checkWifiPassword, type SetupStep } from "../lib/boxsetup";
  import { setUpNetwork } from "../lib/api";
  import { isCountry } from "../lib/countries";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { boxSetup, guessCountry } from "../lib/setup.svelte";

  const t = $derived(i18n.t);
  const network = $derived(live.app.network ?? null);
  const ap = $derived(network?.ap_ssid ?? "NOCS");
  const current = $derived(live.app.system?.hostname ?? "nocs");
  const rename = $derived(auth.owner && (live.app.system?.operations.includes("hostname.set") ?? false));
  const steps = $derived(setupSteps({ rename }));

  let index = $state(0);
  const step = $derived<SetupStep>(steps[Math.min(index, steps.length - 1)] ?? "review");

  let country = $state(guessCountry());
  let password = $state("");
  let joining = $state(false);
  let ssid = $state("");
  let wifiPassword = $state("");
  let openNetwork = $state(false);
  // Starts as the box's name now; the owner may keep it.
  let name = $state<string | null>(null);
  const nameShown = $derived(name ?? current);
  const host = $derived((rename ? hostName(nameShown) : null) ?? current);
  const join = $derived(joining && ssid.trim() ? ssid.trim() : null);
  // The box on its access point (this phone, most likely, on it too); otherwise on a
  // network or a cable, where the access point takes the new password next time.
  const onAp = $derived(network?.mode === "ap");

  let busy = $state(false);
  let error = $state("");
  let fieldError = $state("");

  const countryName = $derived(
    new Intl.DisplayNames([i18n.locale], { type: "region" }).of(country) ?? country,
  );

  function passwordProblem(value: string): string {
    const problem = checkWifiPassword(value);
    if (problem === "short") return t.boxSetup.passwordShort;
    if (problem === "long") return t.boxSetup.passwordLong;
    if (problem === "ascii") return t.boxSetup.passwordAscii;
    return "";
  }

  // The current step's own check before the next one: its message, or "".
  function check(): string {
    if (step === "accessPoint") return passwordProblem(password);
    if (step === "wifi" && joining) {
      if (!ssid.trim()) return t.boxSetup.ssidMissing;
      if (!openNetwork) return passwordProblem(wifiPassword);
    }
    if (step === "name" && hostName(nameShown) === null) return t.system.nameInvalid;
    return "";
  }

  let heading = $state<HTMLHeadingElement>();

  function go(to: number): void {
    error = "";
    fieldError = "";
    index = Math.max(0, Math.min(to, steps.length - 1));
    // The new step's title takes the focus, so a screen reader starts there.
    queueMicrotask(() => heading?.focus());
  }

  async function next(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = "";
    fieldError = check();
    if (fieldError || (step === "accessPoint" && !isCountry(country))) return;
    if (step !== "review") {
      go(index + 1);
      return;
    }
    if (!isCountry(country)) return;
    const wanted = rename ? hostName(nameShown) : null;
    const renamed = wanted !== null && wanted !== current;
    busy = true;
    try {
      await setUpNetwork({
        country,
        password,
        join: join ? { ssid: join, password: openNetwork ? null : wifiPassword || null } : null,
        hostname: renamed ? wanted : null,
      });
      boxSetup.done = { ssid: join, accessPoint: ap, host, renamed, onAp };
      password = wifiPassword = "";
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

<div class="screen">
  <header class="top">
    <span class="brand"><Icon name="logo" size={32} /><span class="wordmark">NOCS</span></span>
    <ThemeButton />
  </header>

  {#if boxSetup.done}
    {@const done = boxSetup.done}
    <div class="intro">
      <h1 class="display">{t.boxSetup.doneTitle}</h1>
      <p class="body">
        {done.ssid
          ? t.boxSetup.doneJoin(done.ssid, done.accessPoint, done.host)
          : done.onAp
            ? t.boxSetup.doneAp(done.accessPoint, done.host)
            : t.boxSetup.doneKeep(done.accessPoint, done.host)}
      </p>
      {#if done.renamed}<p class="body">{t.boxSetup.pairAgain}</p>{/if}
    </div>
    <div class="actions">
      <Button variant="primary" wide onclick={() => (boxSetup.done = null)}>{t.boxSetup.continue}</Button>
    </div>
  {:else}
    <form class="form" onsubmit={next} novalidate>
      <div class="progress">
        <p class="caption muted">
          {t.boxSetup.stepOf(index + 1, steps.length)} · {t.boxSetup.title}
        </p>
        <ol class="steps" style:grid-template-columns="repeat({steps.length}, 1fr)">
          {#each steps as s, i (s)}
            <li class:done={i < index} class:current={i === index} aria-current={i === index ? "step" : undefined}>
              <span class="visually-hidden">{t.boxSetup.steps[s]}</span>
            </li>
          {/each}
        </ol>
      </div>

      <div class="intro">
        <h1 class="display" tabindex="-1" bind:this={heading}>{t.boxSetup.steps[step]}</h1>
        {#if step === "accessPoint"}
          <p class="body">{t.boxSetup.body(ap)}</p>
        {:else if step === "wifi"}
          <p class="body">{t.boxSetup.wifiBody}</p>
        {:else if step === "name"}
          <p class="body">{t.boxSetup.nameBody}</p>
        {:else}
          <p class="body">{t.boxSetup.reviewBody}</p>
        {/if}
      </div>

      {#if step === "accessPoint"}
        <Banner icon="alert" tone="warning">{t.boxSetup.usb}</Banner>
        <CountrySelect label={t.boxSetup.country} hint={t.boxSetup.countryHint} bind:value={country} />
        <TextField
          label={t.boxSetup.password}
          hint={t.boxSetup.passwordHint}
          error={fieldError || undefined}
          type="password"
          autocomplete="new-password"
          bind:value={password}
          required
          minlength={8}
          maxlength={63} />
      {:else if step === "wifi"}
        <Toggle
          label={t.boxSetup.joinToggle}
          hint={t.boxSetup.joinToggleHint}
          checked={joining}
          onchange={(on) => {
            joining = on;
            fieldError = "";
          }} />
        {#if joining}
          <WifiPicker label={t.boxSetup.ssid} bind:value={ssid} bind:open={openNetwork} />
          {#if !openNetwork}
            <TextField
              label={t.boxSetup.wifiPassword}
              type="password"
              autocomplete="off"
              bind:value={wifiPassword}
              maxlength={63} />
          {/if}
          {#if fieldError}<Banner icon="alert" tone="error">{fieldError}</Banner>{/if}
        {/if}
      {:else if step === "name"}
        <TextField
          label={t.boxSetup.name}
          hint={t.boxSetup.nameHint(hostName(nameShown) ?? "…")}
          error={fieldError || undefined}
          autocomplete="off"
          bind:value={() => nameShown, (v) => (name = v)}
          required
          maxlength={63} />
      {:else}
        <dl class="summary">
          <div>
            <dt class="label muted">{t.boxSetup.accessPoint}</dt>
            <dd>{t.boxSetup.accessPointValue(ap, countryName)}</dd>
          </div>
          <div>
            <dt class="label muted">{t.boxSetup.homeWifi}</dt>
            <dd>{join ?? t.boxSetup.noWifi}</dd>
          </div>
          <div>
            <dt class="label muted">{t.boxSetup.address}</dt>
            <dd class="mono">http://{host}.local</dd>
          </div>
        </dl>
        <p class="body note">
          {join
            ? t.boxSetup.afterJoin(join, ap, host)
            : onAp
              ? t.boxSetup.afterAp(ap, host)
              : t.boxSetup.afterKeep(ap, host)}
          {#if host !== current}{t.boxSetup.pairAgain}{/if}
        </p>
      {/if}

      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

      <div class="actions">
        {#if index > 0}
          <Button variant="secondary" disabled={busy} onclick={() => go(index - 1)}>
            <Icon name="chevronLeft" size={20} />{t.boxSetup.back}
          </Button>
        {/if}
        <span class="primary">
          <Button
            variant="primary"
            type="submit"
            wide
            {busy}
            disabled={step === "accessPoint" && !isCountry(country)}>
            {step === "review" ? t.boxSetup.submit : t.boxSetup.next}
          </Button>
        </span>
      </div>
    </form>
  {/if}
</div>

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
    max-width: 520px;
    min-height: 100dvh;
    margin: 0 auto;
    padding: calc(var(--space-6) + env(safe-area-inset-top)) var(--margin)
      calc(var(--space-6) + env(safe-area-inset-bottom));
  }
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    color: var(--accent);
  }
  .wordmark {
    color: var(--text);
    font-size: 20px;
    font-weight: 600;
    letter-spacing: 0.12em;
  }
  .form {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
  }
  .progress {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .steps {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .steps li {
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--line);
  }
  .steps .done {
    background: var(--muted);
  }
  .steps .current {
    background: var(--accent);
  }
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .intro {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .intro h1:focus {
    outline: none;
  }
  .body {
    color: var(--muted);
    font-size: 17px;
    line-height: 26px;
  }
  .note {
    font-size: 15px;
    line-height: 22px;
  }
  .summary {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin: 0;
  }
  .summary div {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .summary dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .actions {
    margin-top: auto;
    display: flex;
    gap: var(--space-3);
  }
  .primary {
    flex: 1;
  }
</style>
