<script lang="ts">
  // The histogram of the video's latest frame, over the status bar: 256 bins of the
  // brightest channel on the camera's own scale, linear as recorded. Counts on a
  // logarithmic scale so a planet's few pixels show next to the sky's peak; the last
  // bins are drawn in the warning tone, and the share of saturated pixels said. It
  // folds into a thin bar, as Explore's.
  import Icon from "../../components/Icon.svelte";
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { VideoFrame } from "../../lib/types";

  let { frame, open, ontoggle }: { frame: VideoFrame | null; open: boolean; ontoggle: () => void } = $props();

  const WIDTH = 512;
  const HEIGHT = 64;
  const CLIPPED = 250;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  function area(bins: number[], from: number, to: number): string {
    const top = Math.log1p(Math.max(...bins)) || 1;
    const step = WIDTH / bins.length;
    let path = `M${from * step} ${HEIGHT}`;
    for (let i = from; i < to; i++) {
      const y = HEIGHT - (Math.log1p(bins[i] ?? 0) / top) * HEIGHT;
      path += `L${i * step} ${y}L${(i + 1) * step} ${y}`;
    }
    return `${path}L${to * step} ${HEIGHT}z`;
  }

  const body = $derived(frame ? area(frame.histogram, 0, CLIPPED) : "");
  const clipped = $derived(frame ? area(frame.histogram, CLIPPED, frame.histogram.length) : "");
  const saturated = $derived(
    frame && frame.saturated > 0 ? t.video.saturated(`${formatDecimal(frame.saturated * 100, locale, 2)} %`) : null,
  );
</script>

<div class="histogram" class:open data-overlay>
  <button type="button" class="toggle" aria-expanded={open} onclick={ontoggle}>
    <Icon name={open ? "chevronDown" : "up"} size={18} />
    <span class="caption">{t.live.histogramTitle}</span>
    {#if saturated}<span class="caption warning">{saturated}</span>{/if}
  </button>
  {#if open}
    {#if frame}
      <svg viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" role="img" aria-label={t.live.histogram}>
        <path d={body} class="bins" />
        <path d={clipped} class="clipped" />
      </svg>
    {:else}
      <p class="caption muted">{t.video.noPreview}</p>
    {/if}
  {/if}
</div>

<style>
  .histogram {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: 0 var(--space-3) var(--space-1);
    background: var(--surface);
    border-top: 1px solid var(--line);
  }
  .toggle {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 32px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  svg {
    width: 100%;
    height: 56px;
  }
  .bins {
    fill: color-mix(in srgb, var(--text) 45%, transparent);
  }
  .clipped {
    fill: var(--warning);
  }
  .warning {
    color: var(--warning);
  }
  p {
    margin: 0;
  }
</style>
