<script lang="ts">
  // The running Sun or Moon finder, or the latest one (ADR 0049): where it stands,
  // its frames, how far the disc is from the centre and how far the mount pointed
  // off. Shown in the mount's sheet, which starts it, and in Live view.
  import Chip from "../../components/Chip.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import { formatDecimal, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { FinderState } from "../../lib/types";

  let { finder }: { finder: FinderState } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  function arcmin(value: number): string {
    const size = Math.abs(value);
    return size >= 60 ? `${formatDecimal(size / 60, locale, 2)}°` : `${formatDecimal(size, locale, 1)}′`;
  }

  const status = $derived.by((): { tone: Tone; text: string } => {
    switch (finder.state) {
      case "running":
        return {
          tone: "accent",
          text:
            finder.phase === "searching"
              ? t.finder.searching(finder.searched, finder.positions)
              : t.finder.phases[finder.phase],
        };
      case "succeeded":
        return { tone: "ok", text: t.finder.centred };
      case "cancelled":
        return { tone: "neutral", text: t.finder.cancelled };
      default:
        // Failed: before the disc was seen, or after (measuring the axes, centring).
        return {
          tone: "error",
          text: finder.phase === "tracking" || finder.phase === "searching" ? t.finder.notFound : t.finder.notCentred,
        };
    }
  });
  const pointedOff = $derived(
    finder.state === "succeeded" && finder.offset ? Math.hypot(finder.offset.east, finder.offset.north) : null,
  );
</script>

<section class="finder" aria-labelledby="finder-card-title">
  <div class="header">
    <h3 class="label muted" id="finder-card-title">{t.finder.bodies[finder.body]}</h3>
    <Chip tone={status.tone}>{status.text}</Chip>
  </div>
  <p class="caption muted">{t.finder.frames(finder.frames, formatPlain(finder.exposure, locale, 4), finder.binning)}</p>
  {#if finder.error !== null}<p class="mono">{t.finder.fromCentre(arcmin(finder.error))}</p>{/if}
  {#if pointedOff !== null}<p class="caption">{t.finder.pointedOff(arcmin(pointedOff))}</p>{/if}
  {#if finder.state === "succeeded" && finder.track_mode}
    <p class="caption">{t.finder.tracking(t.mount.modes[finder.track_mode] ?? finder.track_mode)}</p>
  {/if}
  {#if finder.synced}<p class="caption">{t.finder.synced}</p>{/if}
  {#if finder.warning}<p class="caption warning">{finder.warning}</p>{/if}
  {#if finder.failure}<p class="caption error">{finder.failure}</p>{/if}
</section>

<style>
  .finder {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
  }
  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  h3,
  p {
    margin: 0;
  }
  .warning {
    color: var(--warning);
  }
  .error {
    color: var(--error);
  }
</style>
