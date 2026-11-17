<script lang="ts">
  // The histogram of the frame on screen, over the status bar (ADR 0054). Counts on a
  // logarithmic scale so faint tails stay visible next to the sky's peak. The image
  // is already stretched: "Full" spans the camera's whole scale (0 to 65535, linear),
  // "Stretch" the part of it where the data is, with the stretch's curve over it.
  // Either way lines mark where the stretch turns each channel black and mid grey.
  // It folds into a thin bar; the choice and the scale are kept per device.
  import Icon from "../../components/Icon.svelte";
  import PillSwitch from "../../components/PillSwitch.svelte";
  import { stretched, type HistogramScale } from "../../lib/explore";
  import { formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { Preview } from "../../lib/types";

  let {
    preview,
    none,
    open,
    scale,
    ontoggle,
    onscale,
  }: {
    // Null while there is none: no frame yet, or the live stack on screen.
    preview: Preview | null;
    // Said instead of the plot meanwhile.
    none: string;
    open: boolean;
    scale: HistogramScale;
    ontoggle: () => void;
    onscale: (scale: HistogramScale) => void;
  } = $props();

  const WIDTH = 512;
  const HEIGHT = 64;
  const FULL = 65536;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  // What the plot spans, in ADU, and its counts.
  const view = $derived.by(() => {
    if (!preview) return null;
    if (scale === "full" && preview.histogram_full.length > 0) {
      return { bins: preview.histogram_full, start: 0, span: FULL };
    }
    return {
      bins: preview.histogram,
      start: preview.histogram_start,
      span: preview.histogram_step * preview.histogram.length,
    };
  });

  function x(value: number): number {
    return view ? ((value - view.start) / view.span) * WIDTH : 0;
  }

  const area = $derived.by(() => {
    if (!view || view.bins.length === 0) return "";
    const top = Math.log1p(Math.max(...view.bins)) || 1;
    const step = WIDTH / view.bins.length;
    const points = view.bins.map((count, i) => {
      const y = HEIGHT - (Math.log1p(count) / top) * (HEIGHT - 2);
      return `${(i * step + step / 2).toFixed(1)} ${y.toFixed(1)}`;
    });
    return `M0 ${HEIGHT}L${points.join("L")}L${WIDTH} ${HEIGHT}Z`;
  });

  // One curve and pair of marks per channel: red, green and blue, or the mono one.
  const channels = $derived(
    (preview?.stretch ?? []).map((stretch, i, all) => ({
      stretch,
      tone: all.length === 1 ? "mono" : (["red", "green", "blue"][i] ?? "mono"),
    })),
  );
  const inside = (position: number) => position >= 0 && position <= WIDTH;

  function curve(stretch: { shadows: number; midtones: number }): string {
    if (!view) return "";
    const points: string[] = [];
    for (let i = 0; i <= 128; i++) {
      const value = view.start + (view.span * i) / 128;
      const y = HEIGHT - stretched(value / (FULL - 1), stretch) * (HEIGHT - 2);
      points.push(`${((i / 128) * WIDTH).toFixed(1)} ${y.toFixed(1)}`);
    }
    return `M${points.join("L")}`;
  }

  const low = $derived(view ? formatPlain(view.start, locale) : "");
  const high = $derived(view ? formatPlain(Math.min(FULL - 1, view.start + view.span - 1), locale) : "");
  const marks = $derived(
    channels.length > 0
      ? t.live.histogramMarks(
          formatPlain(Math.round(channels[0]!.stretch.shadows * (FULL - 1)), locale),
          formatPlain(Math.round(channels[0]!.stretch.midtones * (FULL - 1)), locale),
        )
      : "",
  );
</script>

<section class="histogram" class:open data-overlay aria-label={t.live.histogram}>
  <div class="header">
    <button type="button" class="fold" aria-expanded={open} onclick={ontoggle}>
      <Icon name={open ? "chevronDown" : "up"} size={18} />
      <span>{t.live.histogramTitle}</span>
    </button>
    {#if open && preview}
      <PillSwitch
        label={t.live.histogramScale}
        options={[
          { value: "stretch" as HistogramScale, label: t.live.histogramStretch },
          { value: "full" as HistogramScale, label: t.live.histogramFull },
        ]}
        value={scale}
        onchange={onscale} />
    {/if}
  </div>
  {#if open}
    {#if preview && view}
      <svg viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" role="img" aria-label="{t.live.histogram}. {low} – {high}. {marks}">
        <path class="area" d={area} />
        {#each channels as channel, i (i)}
          {#if scale === "stretch"}<path class="curve {channel.tone}" d={curve(channel.stretch)} />{/if}
          {#each [x(channel.stretch.shadows * (FULL - 1)), x(channel.stretch.midtones * (FULL - 1))] as position, j (j)}
            {#if inside(position)}
              <line class="mark {channel.tone}" class:shadows={j === 0} x1={position} x2={position} y1="0" y2={HEIGHT} />
            {/if}
          {/each}
        {/each}
      </svg>
      <div class="axis caption mono" aria-hidden="true">
        <span>{low}</span>
        <span class="marks">{marks}</span>
        <span>{high}</span>
      </div>
    {:else}
      <p class="caption muted none">{none}</p>
    {/if}
  {/if}
</section>

<style>
  .histogram {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0 var(--space-3) var(--space-1);
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    border-top: 1px solid var(--line);
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-height: var(--touch);
  }
  .fold {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    padding: 0 var(--space-1) 0 0;
    border: 0;
    background: transparent;
    color: var(--muted);
    font-size: 13px;
    cursor: pointer;
  }
  svg {
    display: block;
    width: 100%;
    height: 56px;
  }
  .area {
    fill: color-mix(in srgb, var(--accent) 22%, transparent);
    stroke: var(--accent);
    stroke-width: 1.5;
    stroke-linejoin: round;
    vector-effect: non-scaling-stroke;
  }
  .curve {
    fill: none;
    stroke-width: 1.2;
    opacity: 0.8;
    vector-effect: non-scaling-stroke;
  }
  .mark {
    stroke-width: 1;
    stroke-dasharray: 4 3;
    vector-effect: non-scaling-stroke;
  }
  .mark.shadows {
    stroke-dasharray: none;
  }
  .mono {
    stroke: var(--text);
  }
  .red {
    stroke: var(--channel-red);
  }
  .green {
    stroke: var(--channel-green);
  }
  .blue {
    stroke: var(--channel-blue);
  }
  .axis {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    color: var(--muted);
  }
  .marks {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .none {
    margin: 0;
    padding-bottom: var(--space-1);
  }
</style>
