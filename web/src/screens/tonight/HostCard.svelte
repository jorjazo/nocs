<script lang="ts">
  // Tonight's "Host" card: how the box is doing (CPU, memory, room for frames and on
  // the system disk, its sensors) and who is connected: the owner sees each paired
  // device, observers only how many watch (ADR 0047). Closed: the CPU, the memory
  // and the room for frames, with a chip when Rig's Status or Storage would show one.
  import Section from "../../components/Section.svelte";
  import { formatBytes, formatPlain, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { storageAttention, systemAttention } from "../../lib/rigsections";

  let { open, ontoggle }: { open: boolean; ontoggle: (open: boolean) => void } = $props();

  const t = $derived(i18n.t);
  const h = $derived(t.tonight.host);
  const locale = $derived(i18n.locale);
  const system = $derived(live.app.system ?? null);
  const health = $derived(system?.health ?? null);
  const storage = $derived(live.app.storage ?? null);
  const frames = $derived(storage?.destinations.find((d) => d.id === storage.destination) ?? null);
  const clients = $derived(live.app.clients ?? null);

  const readouts = $derived.by(() => {
    const items: { label: string; value: string; low?: boolean }[] = [];
    if (!health) return items;
    if (health.cpu_used !== null) items.push({ label: h.cpu, value: `${health.cpu_used} %` });
    if (health.memory_used !== null) items.push({ label: t.system.memory, value: `${health.memory_used} %` });
    if (frames) items.push({ label: h.frames, value: t.system.free(formatBytes(frames.free, locale)) });
    if (health.disk_free !== null && !frames?.system) {
      items.push({ label: t.system.disk, value: t.system.free(formatBytes(health.disk_free, locale)) });
    }
    if (health.cpu_temperature !== null) {
      items.push({ label: h.cpuTemperature, value: formatTemperature(health.cpu_temperature, locale, 0) });
    }
    if (health.fan !== null) items.push({ label: t.system.fan, value: t.system.rpm(formatPlain(health.fan, locale)) });
    if (health.under_voltage !== null) {
      const low = health.under_voltage;
      items.push({ label: t.system.supply, value: low ? t.system.supplyLow : t.system.supplyOk, low });
    }
    if (health.throttled) items.push({ label: h.speed, value: h.throttled, low: true });
    return items;
  });

  const summary = $derived(
    [
      health?.cpu_used != null ? h.cpuUsed(String(health.cpu_used)) : null,
      health?.memory_used != null ? h.memoryUsed(String(health.memory_used)) : null,
      frames ? t.system.free(formatBytes(frames.free, locale)) : null,
    ]
      .filter((part) => part !== null)
      .join(" · ") || null,
  );
  const status = $derived.by(() => {
    const worst = [systemAttention(system), storageAttention(storage, live.app.share)];
    if (worst.includes("problem")) return { tone: "error" as const, text: t.rig.attention.problem };
    if (worst.includes("warning")) return { tone: "warning" as const, text: t.rig.attention.warning };
    return null;
  });
</script>

<Section scope="tonight" id="host" title={h.title} {summary} {status} {open} {ontoggle}>
  {#if readouts.length}
    <dl class="readouts">
      {#each readouts as item (item.label + item.value)}
        <div>
          <dt class="label muted">{item.label}</dt>
          <dd class:low={item.low}>{item.value}</dd>
        </div>
      {/each}
    </dl>
  {/if}
  {#each health?.warnings ?? [] as warning (warning)}
    <p class="warning small">{t.system.warnings[warning]}</p>
  {/each}
  {#if clients}
    <div class="group">
      <h3 class="label">{h.clients}</h3>
      {#each clients.devices as device (device.id)}
        <div class="row">
          <span>{device.name}</span>
          {#if device.connections > 1}<span class="muted">{h.pages(device.connections)}</span>{/if}
        </div>
      {/each}
      {#if clients.observers > 0}
        <span>{h.observers(clients.observers)}</span>
      {:else if clients.devices.length === 0}
        <span class="muted">{h.nobody}</span>
      {/if}
    </div>
  {/if}
</Section>

<style>
  .readouts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: var(--space-3);
    margin: 0;
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  dd {
    margin: 0;
  }
  .low,
  .warning {
    color: var(--warning);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h3 {
    margin: 0;
    color: var(--muted);
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .small {
    font-size: 13px;
  }
  p {
    margin: 0;
  }
</style>
