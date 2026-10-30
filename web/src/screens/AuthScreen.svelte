<script lang="ts">
  // First run (create the owner passphrase, which also pairs this device) and
  // pairing with that passphrase: the same full-screen form (ADR 0014).
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import TextField from "../components/TextField.svelte";
  import ThemeButton from "../components/ThemeButton.svelte";
  import { ApiError } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { suggestDeviceName } from "../lib/device";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { LOCALES, prefs } from "../lib/prefs.svelte";

  let { mode }: { mode: "setup" | "pair" } = $props();

  const t = $derived(i18n.t);
  const setup = $derived(mode === "setup");

  let name = $state("");
  // Follow the language with the suggested name until the user edits it.
  let suggested = "";
  $effect(() => {
    const suggestion = suggestDeviceName(i18n.t);
    if (name === suggested) name = suggestion;
    suggested = suggestion;
  });
  let passphrase = $state("");
  let busy = $state(false);
  let error = $state("");
  let passphraseError = $state("");
  let lockedUntil = $state(0);
  let now = $state(Date.now());

  const lockedFor = $derived(Math.max(0, Math.ceil((lockedUntil - now) / 1000)));
  $effect(() => {
    if (lockedUntil <= Date.now()) return;
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = "";
    passphraseError = "";
    // The server counts characters after NFC normalization.
    if ([...passphrase.normalize("NFC")].length < 8) {
      passphraseError = t.passphrase.tooShort;
      return;
    }
    busy = true;
    try {
      if (setup) await auth.setUp(passphrase, name.trim());
      else await auth.pair(passphrase, name.trim());
      passphrase = "";
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        passphraseError = t.passphrase.wrong;
      } else if (e instanceof ApiError && e.status === 429) {
        lockedUntil = Date.now() + (e.retryAfter ?? 60) * 1000;
        now = Date.now();
      } else if (e instanceof ApiError && e.status === 409) {
        // Someone else set it up first, or it was reset: ask again.
        await auth.refresh();
      } else {
        error = errorText(e, t);
      }
    } finally {
      busy = false;
    }
  }
</script>

<div class="screen">
  <header class="top">
    <span class="brand"><Icon name="logo" size={40} /><span class="wordmark">NOCS</span></span>
    <span class="prefs">
      <SegmentedControl
        label={t.language.label}
        options={LOCALES.map((locale) => ({ value: locale, label: locale.toUpperCase() }))}
        value={prefs.locale}
        onchange={(locale) => prefs.setLocale(locale)} />
      <ThemeButton />
    </span>
  </header>

  <form class="form" onsubmit={submit} novalidate>
    <div class="intro">
      <h1 class="display">{setup ? t.firstRun.title : t.pair.title}</h1>
      <p class="body">{setup ? t.firstRun.body : t.pair.body}</p>
    </div>

    {#if auth.revoked && !setup}
      <Banner icon="alert" tone="warning">{t.pair.revoked}</Banner>
    {/if}

    <TextField label={t.device.name} hint={t.device.nameHint} bind:value={name} required maxlength={64} />
    <TextField
      label={t.passphrase.label}
      hint={setup ? t.firstRun.passphraseHint : undefined}
      error={passphraseError || (lockedFor ? t.passphrase.locked(lockedFor) : undefined)}
      type="password"
      autocomplete={setup ? "new-password" : "current-password"}
      bind:value={passphrase}
      required
      minlength={8} />

    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

    <div class="actions">
      <Button variant="primary" type="submit" wide {busy} disabled={!name.trim() || lockedFor > 0}>
        {setup ? t.firstRun.submit : t.pair.submit}
      </Button>
      {#if !setup && auth.status?.observer}
        <Button variant="text" wide onclick={() => (auth.wantsPair = false)}>{t.pair.watch}</Button>
      {/if}
    </div>
  </form>
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
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
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
  .prefs {
    display: flex;
    align-items: center;
    gap: var(--space-2);
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
  .actions {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
</style>
