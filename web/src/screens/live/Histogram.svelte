<script lang="ts">
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { Preview } from "../../lib/types";

  // Histogram of the linear frame, counts on a logarithmic scale so faint
  // tails stay visible next to the sky peak. The server chooses the bins over
  // where the data is, with a margin at both sides; dotted lines mark the
  // darkest and brightest values when they fall inside.
  let { preview, label, note }: { preview: Preview; label: string; note: string } = $props();

  const WIDTH = 256;
  const HEIGHT = 64;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const bins = $derived(preview.histogram);
  const start = $derived(preview.histogram_start);
  const span = $derived(preview.histogram_step * bins.length);

  // Position of a value (ADU) on the plot.
  function x(value: number): number {
    return ((value - start) / span) * WIDTH;
  }

  const path = $derived.by(() => {
    if (bins.length === 0) return "";
    const top = Math.log1p(Math.max(...bins)) || 1;
    const step = WIDTH / bins.length;
    const points = bins.map((count, i) => {
      const y = HEIGHT - (Math.log1p(count) / top) * (HEIGHT - 2);
      return `${(i * step + step / 2).toFixed(1)} ${y.toFixed(1)}`;
    });
    return `M0 ${HEIGHT}L${points.join("L")}L${WIDTH} ${HEIGHT}Z`;
  });

  const markers = $derived(
    [x(preview.minimum), x(preview.maximum + 1)].filter((position) => position >= 0 && position <= WIDTH),
  );
  const minimum = $derived(t.live.histogramMin(formatPlain(preview.minimum, locale)));
  const maximum = $derived(t.live.histogramMax(formatPlain(preview.maximum, locale)));
</script>

<figure class="histogram">
  <div class="plot">
    <svg viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" role="img" aria-label="{label}. {minimum}, {maximum}">
      <path class="area" d={path} />
      {#each markers as position, i (i)}
        <line class="marker" x1={position} x2={position} y1="0" y2={HEIGHT} />
      {/each}
    </svg>
    <span class="caption note">{note}</span>
  </div>
  <figcaption class="caption mono" aria-hidden="true">
    <span>{minimum}</span>
    <span>{maximum}</span>
  </figcaption>
</figure>

<style>
  .histogram {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--surface);
    border: 1px solid var(--line);
  }
  .plot {
    position: relative;
    height: 52px;
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
  }
  .area {
    fill: color-mix(in srgb, var(--accent) 22%, transparent);
    stroke: var(--accent);
    stroke-width: 1.5;
    stroke-linejoin: round;
    vector-effect: non-scaling-stroke;
  }
  .marker {
    stroke: var(--muted);
    stroke-width: 1;
    stroke-dasharray: 3 3;
    vector-effect: non-scaling-stroke;
  }
  .note {
    position: absolute;
    top: 0;
    right: 0;
    color: var(--muted);
  }
  figcaption {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    color: var(--muted);
  }
</style>
