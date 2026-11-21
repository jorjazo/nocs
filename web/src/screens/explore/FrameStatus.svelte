<script lang="ts">
  // The status bar under the image (ADR 0054): the camera and its temperature, what
  // it is doing, then the frame on screen (its size, stars, HFR and exposure, or the
  // stack's), where it points when solved, and how long until the mount reaches the
  // meridian. One line that scrolls sideways when the screen is narrow.
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import { untilMeridian } from "../../lib/explore";
  import { formatDecimal, formatDuration, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { formatDec, formatRa } from "../../lib/mount.svelte";
  import type { CameraState, MountState, Preview } from "../../lib/types";

  let {
    camera,
    preview,
    stack = null,
    status,
    solved = null,
    mount = null,
    longitude = null,
    items = [],
  }: {
    camera: CameraState;
    // The frame on screen, or the stack's picture when that is shown instead.
    preview: Preview | null;
    stack?: { frames: number; exposure: number } | null;
    // What the camera is doing; null when it is free.
    status: { tone: Tone; text: string } | null;
    // Where the frame on screen points, when it was solved.
    solved?: { ra: number; dec: number } | null;
    mount?: MountState | null;
    // Of the site, for the meridian; null without one.
    longitude?: number | null;
    // Figures of a screen with frames of its own (Video's), in place of the preview's.
    items?: string[];
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const temperature = $derived.by(() => {
    if (camera.temperature === null) return null;
    const now = formatTemperature(camera.temperature, locale);
    const cooling = camera.can_cool && (camera.cooler ?? camera.target !== null) && camera.target !== null;
    return cooling ? t.live.statusBar.cooling(now, formatTemperature(camera.target ?? 0, locale, 0)) : now;
  });

  const size = $derived.by(() => {
    if (!preview || preview.frame_width === 0) return null;
    const pixels = t.live.statusBar.size(preview.frame_width, preview.frame_height);
    return preview.binning === null ? pixels : `${pixels} · ${t.live.statusBar.binning(preview.binning)}`;
  });
  const metrics = $derived.by(() => {
    if (!preview) return "";
    const hfr = preview.hfr === null ? "HFR —" : `HFR ${formatDecimal(preview.hfr, locale, 2)}`;
    return [t.live.stars(preview.stars), hfr, formatSeconds(preview.exposure, locale)].join(" · ");
  });

  // The meridian moves with the clock: read it again every half minute.
  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(timer);
  });
  const meridian = $derived.by(() => {
    if (!mount || longitude === null || mount.parked) return null;
    const hours = untilMeridian(mount.ra, longitude, new Date(now));
    const text = formatDuration(Math.abs(hours) * 3600);
    return hours >= 0 ? t.live.statusBar.toMeridian(text) : t.live.statusBar.pastMeridian(text);
  });
</script>

<div class="status" role="group" aria-label={t.live.statusBar.label} data-overlay>
  <span class="item device">
    <span class="name">{camera.device}</span>
    {#if temperature}<span class="mono">{temperature}</span>{/if}
  </span>
  <span class="item" role="status">
    <Chip tone={status?.tone ?? "neutral"}>{status?.text ?? t.live.status.idle}</Chip>
  </span>
  {#if stack}
    <span class="item mono">{t.stack.frames(stack.frames)} · {formatDuration(stack.exposure)}</span>
  {:else if preview}
    {#if size}<span class="item mono">{size}</span>{/if}
    <span class="item mono">{metrics}</span>
  {/if}
  {#each items as item, i (i)}<span class="item mono">{item}</span>{/each}
  {#if solved}
    <span class="item mono">{formatRa(solved.ra)} {formatDec(solved.dec)}</span>
  {/if}
  {#if meridian}<span class="item">{meridian}</span>{/if}
  {#if !preview && !stack && items.length === 0}<span class="item muted">{t.live.noPreview}</span>{/if}
</div>

<style>
  .status {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 40px;
    padding: 0 var(--space-3);
    overflow-x: auto;
    scrollbar-width: none;
    background: var(--surface);
    border-top: 1px solid var(--line);
    font-size: 14px;
    white-space: nowrap;
  }
  .status::-webkit-scrollbar {
    display: none;
  }
  .item {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    flex: none;
  }
  .item + .item {
    padding-left: var(--space-3);
    border-left: 1px solid var(--line);
  }
  .name {
    font-weight: 600;
  }
</style>
