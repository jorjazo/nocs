<script lang="ts">
  // Rig → Access, for the owner: change the owner passphrase (ADR 0014). On the
  // appliance it is also the SSH login's password (ADR 0043), which entering the
  // current passphrase as the new one sets when it is not set yet.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import TextField from "../components/TextField.svelte";
  import { ApiError, changePassphrase } from "../lib/api";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { changeProblems, loginWarning, type ChangeProblems } from "../lib/passphrase";
  import { passphraseForm } from "../lib/passphraseform.svelte";

  const t = $derived(i18n.t);

  const login = $derived(live.app.system?.login ?? null);
  const hostname = $derived(live.app.system?.hostname ?? "nocs");
  const warning = $derived(loginWarning(login));

  let current = $state("");
  let next = $state("");
  let again = $state("");
  let problems = $state<ChangeProblems>({});
  let busy = $state(false);
  let error = $state("");
  let wrong = $state(false);
  let lockedUntil = $state(0);
  let now = $state(Date.now());
  let changed = $state(false);
  let section = $state<HTMLElement>();

  const lockedFor = $derived(Math.max(0, Math.ceil((lockedUntil - now) / 1000)));
  $effect(() => {
    if (lockedUntil <= Date.now()) return;
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  // "This computer" asked for the form: bring it into view (once per ask, not on
  // every visit to Rig).
  let shown = passphraseForm.shown;
  $effect(() => {
    if (passphraseForm.shown === shown) return;
    shown = passphraseForm.shown;
    changed = false;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    section?.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
  });

  function reset(): void {
    current = next = again = "";
    problems = {};
    error = "";
    wrong = false;
  }

  function close(): void {
    reset();
    passphraseForm.open = false;
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = "";
    wrong = false;
    changed = false;
    problems = changeProblems({ current, next, again });
    if (Object.keys(problems).length > 0) return;
    busy = true;
    try {
      await changePassphrase({ current, new: next });
      close();
      changed = true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        wrong = true;
      } else if (e instanceof ApiError && e.status === 429) {
        lockedUntil = Date.now() + (e.retryAfter ?? 60) * 1000;
        now = Date.now();
      } else {
        error = errorText(e, t);
      }
    } finally {
      busy = false;
    }
  }

  const currentError = $derived(
    lockedFor
      ? t.passphrase.locked(lockedFor)
      : wrong
        ? t.passphrase.wrong
        : problems.current
          ? t.access.currentMissing
          : undefined,
  );
  const nextError = $derived(
    problems.next === "tooShort" ? t.passphrase.tooShort : problems.next === "tooLong" ? t.passphrase.tooLong : undefined,
  );
</script>

<div class="passphrase" bind:this={section}>
  <div class="line">
    <h3 class="label muted">{t.access.passphrase}</h3>
    {#if !passphraseForm.open}
      <Button
        variant="text"
        onclick={() => {
          changed = false;
          passphraseForm.open = true;
        }}>{t.access.changePassphrase}</Button>
    {/if}
  </div>
  <p class="caption muted">{t.access.passphraseHint}</p>
  {#if login}<p class="caption muted">{t.access.sshNote(login.user, hostname)}</p>{/if}

  {#if passphraseForm.open}
    <form class="form" onsubmit={submit} novalidate>
      {#if login && warning}<p class="muted">{t.access.resyncHint(login.user)}</p>{/if}
      <TextField
        label={t.access.current}
        type="password"
        autocomplete="current-password"
        error={currentError}
        bind:value={current}
        required />
      <TextField
        label={t.access.next}
        hint={t.access.nextHint}
        type="password"
        autocomplete="new-password"
        error={nextError}
        bind:value={next}
        required
        minlength={8}
        maxlength={1024} />
      <TextField
        label={t.access.again}
        type="password"
        autocomplete="new-password"
        error={problems.again ? t.access.mismatch : undefined}
        bind:value={again}
        required
        maxlength={1024} />
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      <div class="buttons">
        <Button variant="primary" type="submit" {busy} disabled={lockedFor > 0}>{t.access.save}</Button>
        <Button variant="text" onclick={close}>{t.access.cancel}</Button>
      </div>
    </form>
  {/if}

  {#if changed}
    <p class="muted" role="status">
      {t.access.changed}
      {#if login?.password === "set"}{t.access.changedSsh(login.user)}{/if}
    </p>
    {#if login?.password === "failed"}
      <Banner icon="alert" tone="warning">{t.system.loginFailed(login.user)}</Banner>
    {/if}
  {/if}
</div>

<style>
  .passphrase {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--line);
    scroll-margin-top: var(--space-8);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  h3 {
    margin: 0;
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding-top: var(--space-2);
  }
  .buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
</style>
