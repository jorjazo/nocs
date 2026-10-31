<script lang="ts">
  // Rig's USB drives: the mounted ones with Eject where nocs-system can eject
  // them, and the ones plugged in but not mounted, with the reason (ADR 0027).
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import DeviceRow from "../components/DeviceRow.svelte";
  import { ApiError, ejectDrive } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { formatBytes } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const storage = $derived(live.app.storage ?? null);
  const drives = $derived((storage?.destinations ?? []).filter((d) => d.removable));
  const unmounted = $derived(storage?.unmounted ?? []);
  // Where NOCS mounts drives itself, one that is not mounted and has no error
  // was ejected and is still plugged in.
  const automount = $derived(live.app.system?.operations.includes("storage.mount") ?? false);

  let busy = $state<string | null>(null);
  let error = $state("");
  // Refused because a job runs: offer to eject anyway.
  let refused = $state<string | null>(null);
  let ejected = $state<string | null>(null);

  async function eject(id: string, label: string, force = false): Promise<void> {
    busy = id;
    error = "";
    refused = null;
    ejected = null;
    try {
      await ejectDrive(id, force);
      ejected = label;
    } catch (e) {
      error = errorText(e, t);
      // A frame being saved refuses a forced eject too: the message says to retry.
      if (e instanceof ApiError && e.status === 409 && !force) refused = id;
    } finally {
      busy = null;
    }
  }
</script>

{#if drives.length > 0 || unmounted.length > 0}
  <h3 class="label muted subsection">{t.drives.title}</h3>
  <ul class="rows">
    {#each drives as drive (drive.id)}
      <DeviceRow icon="storage" title={drive.label} subtitle="{drive.fs} · {formatBytes(drive.free, locale)}">
        {#snippet trailing()}
          {#if drive.ejectable && auth.owner}
            {#if refused === drive.id}
              <ConfirmButton
                label={t.drives.ejectAnyway}
                confirmLabel={t.drives.confirmEject}
                busy={busy === drive.id}
                onconfirm={() => eject(drive.id, drive.label, true)} />
            {:else}
              <Button busy={busy === drive.id} onclick={() => eject(drive.id, drive.label)}>{t.drives.eject}</Button>
            {/if}
          {/if}
        {/snippet}
      </DeviceRow>
    {/each}
    {#each unmounted as drive (drive.device)}
      <DeviceRow
        icon="storage"
        title={drive.label}
        subtitle={drive.error ? undefined : automount ? t.drives.unplug : drive.fs || undefined}
        error={drive.error}>
        {#snippet trailing()}<Chip>{t.drives.notMounted}</Chip>{/snippet}
      </DeviceRow>
    {/each}
  </ul>
  {#if error}<p class="error">{error}</p>{/if}
  {#if ejected}<p class="muted" role="status">{t.drives.ejected(ejected)}</p>{/if}
{/if}

<style>
  .subsection {
    margin: var(--space-4) 0 0;
  }
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
</style>
