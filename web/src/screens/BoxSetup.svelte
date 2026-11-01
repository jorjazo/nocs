<script lang="ts">
  // The appliance's first run (ADR 0028), right after the owner pairs: the access
  // point's country and own password, and maybe a home network. Full screen, before
  // anything else, while the access point keeps its default password.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import TextField from "../components/TextField.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { setUpNetwork } from "../lib/api";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { boxSetup, guessCountry } from "../lib/setup.svelte";

  const t = $derived(i18n.t);
  const network = $derived(live.app.network ?? null);
  const ap = $derived(network?.ap_ssid ?? "NOCS");
  const host = $derived(live.app.system?.hostname ?? "nocs");

  let country = $state(guessCountry());
  let password = $state("");
  let joining = $state(false);
  let ssid = $state("");
  let wifiPassword = $state("");
  let busy = $state(false);
  let error = $state("");
  let passwordError = $state("");

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = "";
    passwordError = "";
    if (password.length < 8) {
      passwordError = t.boxSetup.passwordShort;
      return;
    }
    const join = joining && ssid.trim() ? { ssid: ssid.trim(), password: wifiPassword || null } : null;
    busy = true;
    try {
      await setUpNetwork({ country: country.trim().toUpperCase(), password, join });
      boxSetup.done = { ssid: join?.ssid ?? null, accessPoint: ap, host };
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
    <span class="brand"><Icon name="logo" size={40} /><span class="wordmark">NOCS</span></span>
  </header>

  {#if boxSetup.done}
    {@const done = boxSetup.done}
    <div class="intro">
      <h1 class="display">{t.boxSetup.doneTitle}</h1>
      <p class="body">
        {done.ssid
          ? t.boxSetup.afterJoin(done.ssid, done.accessPoint, done.host)
          : t.boxSetup.afterAp(done.accessPoint, done.host)}
      </p>
    </div>
    <div class="actions">
      <Button variant="primary" wide onclick={() => (boxSetup.done = null)}>{t.boxSetup.continue}</Button>
    </div>
  {:else}
    <form class="form" onsubmit={submit} novalidate>
      <div class="intro">
        <h1 class="display">{t.boxSetup.title}</h1>
        <p class="body">{t.boxSetup.body(ap)}</p>
      </div>

      <TextField label={t.boxSetup.country} hint={t.boxSetup.countryHint} bind:value={country} required maxlength={2} />
      <TextField
        label={t.boxSetup.password}
        hint={t.boxSetup.passwordHint}
        error={passwordError || undefined}
        type="password"
        autocomplete="new-password"
        bind:value={password}
        required
        minlength={8}
        maxlength={63} />

      <Toggle
        label={t.boxSetup.joinToggle}
        hint={t.boxSetup.joinToggleHint}
        checked={joining}
        onchange={(on) => (joining = on)} />
      {#if joining}
        <TextField label={t.boxSetup.ssid} bind:value={ssid} maxlength={32} />
        <TextField label={t.boxSetup.wifiPassword} type="password" autocomplete="off" bind:value={wifiPassword} maxlength={63} />
      {/if}

      <p class="body note">
        {joining && ssid.trim() ? t.boxSetup.afterJoin(ssid.trim(), ap, host) : t.boxSetup.afterAp(ap, host)}
      </p>

      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

      <div class="actions">
        <Button variant="primary" type="submit" wide {busy} disabled={country.trim().length !== 2}>
          {t.boxSetup.submit}
        </Button>
      </div>
    </form>
  {/if}
</div>

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-8);
    max-width: 520px;
    min-height: 100dvh;
    margin: 0 auto;
    padding: calc(var(--space-6) + env(safe-area-inset-top)) var(--margin)
      calc(var(--space-6) + env(safe-area-inset-bottom));
  }
  .top {
    display: flex;
    align-items: center;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    color: var(--accent);
  }
  .wordmark {
    color: var(--text);
    font-size: 22px;
    font-weight: 600;
    letter-spacing: 0.12em;
  }
  .form {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
  }
  .intro {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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
  .actions {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
</style>
