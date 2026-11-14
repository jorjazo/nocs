<script lang="ts">
  // Rig → Settings → Access, for the owner (ADR 0014): this device, whether others
  // may watch without pairing, and the other paired devices. Observers are offered
  // to pair by the app's banner instead.
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import DeviceRow from "../../components/DeviceRow.svelte";
  import Section from "../../components/Section.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { listDevices, revokeDevice, setObserver } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDateTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { PairedDevice } from "../../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  let devices = $state<PairedDevice[] | null>(null);
  let error = $state("");
  let busy = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      devices = await listDevices();
    } catch (e) {
      error = errorText(e, t);
    }
  }
  $effect(() => {
    if (auth.owner) void load();
  });
  const others = $derived((devices ?? []).filter((device) => !device.current));
  const summary = $derived(
    devices
      ? [t.access.others(others.length), auth.status?.observer ? t.access.watching : null].filter(Boolean).join(" · ")
      : null,
  );

  async function access(key: string, action: () => Promise<void>): Promise<void> {
    busy = key;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

{#if auth.owner && auth.status?.device}
  {@const me = auth.status.device}
  <Section id="access" title={t.access.title} {summary}>
    <ul class="rows">
      <DeviceRow icon="device" title={me.name} subtitle="{t.access.thisDevice} · {t.access.pairedSince(formatDateTime(me.created, locale))}">
        {#snippet trailing()}
          <ConfirmButton
            label={t.access.unpair}
            confirmLabel={t.access.confirmUnpair}
            busy={busy === "me"}
            onconfirm={() => access("me", () => auth.unpair())} />
        {/snippet}
      </DeviceRow>
    </ul>
    <div class="toggle-row">
      <Toggle
        label={t.access.observers}
        hint={t.access.observersHint}
        checked={auth.status.observer}
        disabled={busy === "observer"}
        onchange={(enabled) =>
          access("observer", async () => {
            await setObserver(enabled);
            await auth.refresh();
          })} />
    </div>
    <h4 class="label muted subsection">{t.access.devices}</h4>
    {#if devices && others.length === 0}
      <p class="muted">{t.access.noDevices}</p>
    {:else}
      <ul class="rows">
        {#each others as device (device.id)}
          <DeviceRow icon="device" title={device.name} subtitle={t.access.lastUsed(formatDateTime(device.last_used, locale))}>
            {#snippet trailing()}
              <ConfirmButton
                label={t.access.revoke}
                confirmLabel={t.access.confirmRevoke}
                busy={busy === device.id}
                onconfirm={() =>
                  access(device.id, async () => {
                    await revokeDevice(device.id);
                    await load();
                  })} />
            {/snippet}
          </DeviceRow>
        {/each}
      </ul>
    {/if}
    {#if error}<p class="error">{error}</p>{/if}
  </Section>
{/if}

<style>
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .toggle-row {
    padding-bottom: var(--space-2);
    border-bottom: 1px solid var(--line);
  }
  .subsection {
    margin: var(--space-2) 0 0;
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
</style>
