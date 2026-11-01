<script lang="ts">
  // Rig's network, where nocs-system runs it (the appliance, ADR 0028): what the box
  // is on, the networks it joins by itself, joining one, its access point and mode.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import DeviceRow from "../components/DeviceRow.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import TextField from "../components/TextField.svelte";
  import { forgetNetwork, joinNetwork, setAccessPoint, setNetworkMode } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import type { NetworkState } from "../lib/types";

  const t = $derived(i18n.t);
  const network = $derived(live.app.network ?? null);
  const hostname = $derived(live.app.system?.hostname ?? "nocs");

  const where = $derived.by(() => {
    if (!network) return "";
    if (network.mode === "ap") return t.network.ap(network.ap_ssid);
    if (network.mode === "station" && network.ssid) return t.network.station(network.ssid);
    return t.network.none;
  });

  let busy = $state<string | null>(null);
  let error = $state("");
  let note = $state("");

  async function act(key: string, run: () => Promise<void>, done?: string): Promise<boolean> {
    busy = key;
    error = "";
    note = "";
    try {
      await run();
      if (done) note = done;
      return true;
    } catch (e) {
      error = errorText(e, t);
      return false;
    } finally {
      busy = null;
    }
  }

  // -- Joining a network ----------------------------------------------------------

  let ssid = $state("");
  let password = $state("");

  async function join(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const name = ssid.trim();
    if (await act("join", () => joinNetwork(name, password || null), t.network.joinStarted(name))) {
      password = "";
    }
  }

  // -- Access point ---------------------------------------------------------------

  let apName = $state("");
  let apPassword = $state("");
  let country = $state("");
  $effect(() => {
    // Fill the form from the box, once it is known.
    if (network && !apName) apName = network.ap_ssid;
    if (network && !country && network.country !== "00") country = network.country;
  });

  async function saveAccessPoint(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!network) return;
    const body: { ssid?: string; password?: string; country?: string } = {};
    if (apName.trim() && apName.trim() !== network.ap_ssid) body.ssid = apName.trim();
    if (apPassword) body.password = apPassword;
    if (country.trim() && country.trim().toUpperCase() !== network.country) {
      body.country = country.trim().toUpperCase();
    }
    if (Object.keys(body).length === 0) return;
    if (await act("ap", () => setAccessPoint(body), t.network.saved)) apPassword = "";
  }

  const modes = $derived(
    (["auto", "ap", "station"] as const).map((value) => ({ value, label: t.network.modes[value] })),
  );
  const pin = $derived<NetworkState["pin"]>(network?.pin ?? "auto");
</script>

{#if network}
  <section class="network" aria-labelledby="network-title">
    <div class="line">
      <h2 class="heading" id="network-title">{t.network.title}</h2>
      {#if network.ethernet}<Chip tone="ok">{t.network.ethernet}</Chip>{/if}
    </div>
    <p class="where">
      <span>{where}</span>
      {#if network.mode === "ap"}<span class="muted">· {t.network.apClients(network.ap_clients)}</span>{/if}
    </p>
    {#if network.ap_default_password && auth.owner}
      <Banner icon="alert" tone="warning">{t.network.defaultPassword}</Banner>
    {/if}
    {#if network.joining}
      <p class="muted" role="status">{t.network.joining(network.joining)}</p>
    {:else if network.last_join && !network.last_join.ok}
      <p class="error">{t.network.joinFailed(network.last_join.ssid, network.last_join.error ?? "")}</p>
    {/if}

    {#if auth.owner}
      <h3 class="label muted subsection">{t.network.known}</h3>
      {#if network.known.length === 0}
        <p class="muted">{t.network.noKnown}</p>
      {:else}
        <ul class="rows">
          {#each network.known as name (name)}
            <DeviceRow icon="device" title={name}>
              {#snippet trailing()}
                <ConfirmButton
                  label={t.network.forget}
                  confirmLabel={t.network.confirmForget}
                  busy={busy === `forget:${name}`}
                  onconfirm={() => act(`forget:${name}`, () => forgetNetwork(name))} />
              {/snippet}
            </DeviceRow>
          {/each}
        </ul>
      {/if}

      <h3 class="label muted subsection">{t.network.join}</h3>
      <form class="form" onsubmit={join}>
        <TextField label={t.network.ssid} bind:value={ssid} required maxlength={32} />
        <TextField
          label={t.network.password}
          hint={t.network.passwordHint}
          type="password"
          autocomplete="off"
          bind:value={password}
          maxlength={63} />
        {#if ssid.trim()}<p class="caption muted">{t.network.joinHint(ssid.trim(), hostname)}</p>{/if}
        <div><Button variant="primary" type="submit" busy={busy === "join"}>{t.network.joinButton}</Button></div>
      </form>

      <h3 class="label muted subsection">{t.network.accessPoint}</h3>
      <form class="form" onsubmit={saveAccessPoint}>
        <TextField label={t.network.apName} bind:value={apName} maxlength={32} />
        <TextField
          label={t.network.apPassword}
          hint={t.network.apPasswordHint}
          type="password"
          autocomplete="new-password"
          bind:value={apPassword}
          minlength={8}
          maxlength={63} />
        <TextField label={t.network.country} hint={t.network.countryHint} bind:value={country} maxlength={2} />
        <div><Button type="submit" busy={busy === "ap"}>{t.network.save}</Button></div>
      </form>

      <div class="mode">
        <span class="label muted">{t.network.mode}</span>
        <SegmentedControl
          label={t.network.mode}
          options={modes}
          value={pin}
          disabled={busy === "mode"}
          onchange={(value) => act("mode", () => setNetworkMode(value))} />
      </div>
      {#if error}<p class="error">{error}</p>{/if}
      {#if note}<p class="muted" role="status">{note}</p>{/if}
    {/if}
  </section>
{/if}

<style>
  .network {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .where {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    font-size: 17px;
  }
  .subsection {
    margin: var(--space-3) 0 0;
  }
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .mode {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-top: var(--space-2);
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
</style>
