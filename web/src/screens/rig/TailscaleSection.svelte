<script lang="ts">
  // Rig → Tailscale, where Tailscale runs on the box: the tailnet it is on, and on the
  // appliance (nocs-system's tailscale group) joining and leaving it. The owner's
  // devices on that tailnet pair without the passphrase. Observers do not get it.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Section from "../../components/Section.svelte";
  import { tailscaleLogin, tailscaleLogout } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";

  const t = $derived(i18n.t);
  const tailscale = $derived(live.app.tailscale ?? null);
  const can = (op: string) => auth.owner && (live.app.system?.operations.includes(op) ?? false);

  const summary = $derived.by(() => {
    if (!tailscale) return "";
    if (tailscale.state === "running") return tailscale.name ?? t.tailscale.states.running;
    return t.tailscale.states[tailscale.state];
  });

  let busy = $state<"login" | "logout" | null>(null);
  let error = $state("");

  async function act(which: "login" | "logout", run: () => Promise<void>): Promise<void> {
    busy = which;
    error = "";
    try {
      await run();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

{#if tailscale && auth.owner}
  <Section id="tailscale" title={t.tailscale.title} {summary}>
    <p class="where">{t.tailscale.states[tailscale.state]}</p>

    {#if tailscale.state === "running"}
      <dl class="facts">
        {#if tailscale.name}
          <dt>{t.tailscale.address}</dt>
          <dd><code>http://{tailscale.name}</code></dd>
        {/if}
        {#if tailscale.tailnet}
          <dt>{t.tailscale.tailnet}</dt>
          <dd>{tailscale.tailnet}</dd>
        {/if}
      </dl>
      {#if tailscale.user}
        <p class="caption muted">{t.tailscale.pairing(tailscale.user)}</p>
      {:else}
        <Banner icon="alert" tone="warning">{t.tailscale.tagged}</Banner>
      {/if}
    {:else if tailscale.state === "needs_approval"}
      <p class="muted">{t.tailscale.approval}</p>
    {:else if tailscale.auth_url}
      <p>{t.tailscale.signIn}</p>
      <a class="link" href={tailscale.auth_url} target="_blank" rel="noopener noreferrer">{tailscale.auth_url}</a>
    {:else if tailscale.state !== "starting"}
      <p class="muted">{can("tailscale.login") ? t.tailscale.joinHint : t.tailscale.notHere}</p>
    {/if}

    <div class="buttons">
      {#if tailscale.state !== "running" && tailscale.state !== "starting" && can("tailscale.login")}
        <Button variant={tailscale.auth_url ? "secondary" : "primary"} busy={busy === "login"} onclick={() => act("login", tailscaleLogin)}>
          {tailscale.auth_url ? t.tailscale.newLink : t.tailscale.join}
        </Button>
      {/if}
      {#if tailscale.state !== "needs_login" && can("tailscale.logout")}
        <ConfirmButton
          label={t.tailscale.leave}
          confirmLabel={t.tailscale.confirmLeave}
          busy={busy === "logout"}
          onconfirm={() => act("logout", tailscaleLogout)} />
      {/if}
    </div>
    {#if error}<p class="error">{error}</p>{/if}
  </Section>
{/if}

<style>
  .where {
    font-size: 17px;
  }
  .facts {
    display: grid;
    gap: var(--space-1);
    margin: 0;
  }
  .facts dt {
    color: var(--muted);
  }
  .facts dd {
    margin: 0 0 var(--space-2);
    overflow-wrap: anywhere;
  }
  .facts code {
    font-size: 17px;
    user-select: all;
  }
  .link {
    color: var(--accent);
    overflow-wrap: anywhere;
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
