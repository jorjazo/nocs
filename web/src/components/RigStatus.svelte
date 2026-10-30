<script lang="ts">
  // "4/6 online" in every screen's header; one tap leads to Rig.
  import { connectionTone, readyCount } from "../lib/equipment";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { href } from "../lib/router.svelte";
  import Chip, { type Tone } from "./Chip.svelte";

  const equipment = $derived(live.app.equipment);
  const counts = $derived(equipment ? readyCount(equipment) : null);
  const tone = $derived.by((): Tone => {
    if (!equipment || !counts) return "neutral";
    if (equipment.connection !== "connected") return connectionTone(equipment.connection);
    return counts.ready === counts.total ? "ok" : "warning";
  });
</script>

<!-- Hidden while offline: the last known counts may be stale. -->
{#if equipment && counts && live.status === "open"}
  <a class="status" href={href({ screen: "rig" })}>
    <Chip {tone}>
      {equipment.connection === "connected" || equipment.connection === "connecting"
        ? i18n.t.rig.online(counts.ready, counts.total)
        : i18n.t.connection[equipment.connection]}
    </Chip>
  </a>
{/if}

<style>
  .status {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    text-decoration: none;
  }
</style>
