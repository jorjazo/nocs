<script lang="ts">
  // The target of polar alignment: the pole at the centre, the mount's axis as
  // a dot, and its last positions as a fading trail. Seen from behind the
  // mount facing the pole, so the knobs move the dot the way the hand turns
  // them. The radial scale is logarithmic (rings labelled) so a large error
  // and the last arcminute both have room; the tolerance ring is filled.
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { outerRing, place, radius, rings, type AxisError } from "../../lib/polar";
  import { formatAngle } from "./angle";

  let {
    axis,
    trail,
    tolerance,
    latitude,
  }: {
    axis: AxisError;
    // Earlier errors, oldest first.
    trail: AxisError[];
    tolerance: number;
    latitude: number;
  } = $props();

  const R = 100;
  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const aligned = $derived(axis.total <= tolerance);

  // The scale changes only when the error outgrows it or falls well inside,
  // so the target does not breathe with every frame.
  const outer = $derived(outerRing([axis.total, ...trail.slice(-5).map((e) => e.total)], tolerance));
  const circles = $derived(rings(outer, tolerance));
  const dot = $derived(place(axis, outer, tolerance, latitude));
  const path = $derived(
    [...trail.slice(-20), axis]
      .map((e) => place(e, outer, tolerance, latitude))
      .map((p, i) => `${i ? "L" : "M"}${(p.x * R).toFixed(1)},${(-p.y * R).toFixed(1)}`)
      .join(" "),
  );
  const eastRight = $derived(latitude >= 0);

  // Rings are round numbers: 5′, not 5.0′.
  function ringLabel(arcminutes: number): string {
    if (arcminutes >= 60 && arcminutes % 60 === 0) return `${formatDecimal(arcminutes / 60, locale, 0)}°`;
    if (arcminutes >= 1 && arcminutes % 1 === 0) return `${formatDecimal(arcminutes, locale, 0)}′`;
    return formatAngle(arcminutes, locale);
  }
</script>

<figure class="target">
  <svg viewBox="-118 -118 236 236" role="img" aria-label={t.polar.targetLabel(formatAngle(axis.total, locale))}>
    <circle class="zone" class:aligned r={radius(tolerance, outer, tolerance) * R} />
    {#each circles as ring, i (ring)}
      {@const r = radius(ring, outer, tolerance) * R}
      <circle class="ring" class:outer={i === circles.length - 1} {r} />
      <text class="ring-label" x={r * 0.7071 + 2} y={r * 0.7071 + 8}>{ringLabel(ring)}</text>
    {/each}
    <line class="cross" x1={-R} x2={R} y1="0" y2="0" />
    <line class="cross" y1={-R} y2={R} x1="0" x2="0" />
    <text class="compass" x={-R - 8} y="4" text-anchor="end">{eastRight ? t.polar.westShort : t.polar.eastShort}</text>
    <text class="compass" x={R + 8} y="4" text-anchor="start">{eastRight ? t.polar.eastShort : t.polar.westShort}</text>
    <text class="compass" x="0" y={-R - 6} text-anchor="middle">{t.polar.upShort}</text>
    <text class="compass" x="0" y={R + 14} text-anchor="middle">{t.polar.downShort}</text>
    {#if trail.length}<path class="trail" d={path} />{/if}
    <circle class="pole" r="3" />
    <circle class="axis" class:aligned cx={dot.x * R} cy={-dot.y * R} r="7" />
  </svg>
</figure>

<style>
  .target {
    margin: 0;
    display: grid;
    place-items: center;
  }
  svg {
    width: 100%;
    max-width: 360px;
    height: auto;
    overflow: visible;
  }
  .zone {
    fill: color-mix(in srgb, var(--accent) 14%, transparent);
  }
  .zone.aligned {
    fill: color-mix(in srgb, var(--ok) 25%, transparent);
  }
  .ring {
    fill: none;
    stroke: var(--line);
    stroke-dasharray: 3 3;
  }
  .ring.outer {
    stroke-dasharray: none;
  }
  .ring-label,
  .compass {
    fill: var(--muted);
    font-family: var(--font-mono);
    font-size: 9px;
  }
  .compass {
    font-family: var(--font-sans);
    font-size: 11px;
    font-weight: 600;
  }
  .cross {
    stroke: var(--line);
  }
  .trail {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
    stroke-linejoin: round;
    opacity: 0.6;
  }
  .pole {
    fill: var(--text);
  }
  .axis {
    fill: var(--accent);
    stroke: var(--bg);
    stroke-width: 2;
    transition:
      cx 0.4s,
      cy 0.4s;
  }
  .axis.aligned {
    fill: var(--ok);
  }
</style>
