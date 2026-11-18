<script lang="ts">
  // Rig → The box → Storage: where frames are saved and how full it is, the USB
  // drives, and the file share that serves them to computers (ADR 0039).
  import Chip from "../../components/Chip.svelte";
  import DeviceRow from "../../components/DeviceRow.svelte";
  import Section from "../../components/Section.svelte";
  import { formatBytes } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { storageAttention } from "../../lib/rigsections";
  import ShareSection from "./ShareSection.svelte";
  import StorageDrives from "./StorageDrives.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const storage = $derived(live.app.storage ?? null);
  const destination = $derived(storage?.destinations.find((d) => d.id === storage.destination) ?? null);
  const details = $derived.by(() => {
    if (!destination || !storage) return "";
    const parts = [
      destination.sd ? t.rig.storageSd : destination.internal ? t.rig.storageInternal : null,
      destination.system && !destination.internal ? t.rig.storageSystem : null,
      destination.fs,
      storage.choice === "auto" ? t.rig.storageAuto : null,
      destination.writable ? null : t.rig.storageReadOnly,
    ];
    return parts.filter((part) => part !== null).join(" · ");
  });
  const used = $derived(destination && destination.total > 0 ? 1 - destination.free / destination.total : 0);
  const free = $derived(
    destination ? t.rig.storageFree(formatBytes(destination.free, locale), formatBytes(destination.total, locale)) : null,
  );
  const attention = $derived(storageAttention(storage, live.app.share));
</script>

{#if storage}
  <Section
    id="storage"
    title={t.rig.storage}
    summary={destination ? `${destination.label} · ${free}` : t.rig.storageNone}
    status={attention ? { tone: attention === "problem" ? "error" : "warning", text: t.rig.attention[attention] } : null}>
    <ul class="rows">
      {#if destination}
        <DeviceRow icon="storage" title={destination.label} subtitle={details} error={storage.error}>
          {#snippet trailing()}
            <span class="mono free">{formatBytes(destination.free, locale)}</span>
          {/snippet}
        </DeviceRow>
      {:else}
        <DeviceRow icon="storage" title={t.rig.storageNone} error={storage.error}>
          {#snippet trailing()}<Chip tone="error">{t.deviceStatus.error}</Chip>{/snippet}
        </DeviceRow>
      {/if}
    </ul>
    {#if destination}
      <div class="meter-row">
        <div
          class="meter"
          role="meter"
          aria-label={t.rig.storage}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(used * 100)}>
          <span style:width="{Math.round(used * 100)}%"></span>
        </div>
        <span class="caption muted">{free}</span>
      </div>
    {/if}
    <StorageDrives />
    <ShareSection />
  </Section>
{/if}

<style>
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .free {
    color: var(--text);
  }
  .meter-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .meter {
    height: 8px;
    background: var(--raised);
    overflow: hidden;
  }
  .meter span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
</style>
