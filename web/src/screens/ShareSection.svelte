<script lang="ts">
  // Rig's file sharing, where nocs-system runs it (the appliance, ADR 0037): the
  // read-only SMB share of the frames, its switch, how to open it from a computer,
  // the folders shared and the computers connected.
  import Banner from "../components/Banner.svelte";
  import Chip from "../components/Chip.svelte";
  import DeviceRow from "../components/DeviceRow.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { setShare } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";

  const t = $derived(i18n.t);
  const share = $derived(live.app.share ?? null);
  const hostname = $derived(live.app.system?.hostname ?? "nocs");
  const first = $derived(share?.shares[0]?.name ?? "Internal");

  let busy = $state(false);
  let error = $state("");

  async function toggle(on: boolean): Promise<void> {
    busy = true;
    error = "";
    try {
      await setShare(on);
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

{#if share}
  <section class="share" aria-labelledby="share-title">
    <div class="line">
      <h2 class="heading" id="share-title">{t.share.title}</h2>
      {#if share.on && share.running}<Chip tone="ok">{t.share.clients(share.clients)}</Chip>{/if}
    </div>
    {#if auth.owner}
      <Toggle
        label={t.share.toggle}
        hint={t.share.toggleHint}
        checked={share.on}
        disabled={busy}
        onchange={toggle} />
    {/if}
    {#if error}<p class="error">{error}</p>{/if}

    {#if share.on && !share.running}
      <Banner icon="alert" tone="warning">{t.share.notRunning}</Banner>
    {:else if share.on}
      <h3 class="label muted subsection">{t.share.open}</h3>
      <dl class="how">
        <dt>{t.share.windows}</dt>
        <dd><code>\\{hostname}.local\{first}</code></dd>
        <dt>{t.share.mac}</dt>
        <dd><code>smb://{hostname}.local</code></dd>
        <dt>{t.share.linux}</dt>
        <dd><code>smb://{hostname}.local</code></dd>
      </dl>
      <p class="caption muted">{t.share.login}</p>

      <h3 class="label muted subsection">{t.share.folders}</h3>
      <ul class="rows">
        {#each share.shares as folder (folder.volume)}
          <DeviceRow
            icon="storage"
            title={folder.name}
            subtitle={folder.volume === "internal" ? t.share.internal : t.share.drive(folder.label ?? folder.volume)} />
        {/each}
      </ul>
      <p class="caption muted">{t.share.slow}</p>
    {/if}
  </section>
{/if}

<style>
  .share {
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
  .subsection {
    margin: var(--space-3) 0 0;
  }
  .how {
    display: grid;
    gap: var(--space-1);
    margin: 0;
  }
  .how dt {
    color: var(--muted);
  }
  .how dd {
    margin: 0 0 var(--space-2);
  }
  .how code {
    font-size: 17px;
    overflow-wrap: anywhere;
    user-select: all;
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
