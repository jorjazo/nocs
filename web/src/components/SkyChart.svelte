<script lang="ts">
  import { untrack } from "svelte";
  import { getSkyChart } from "../lib/api";
  import { i18n } from "../lib/i18n";
  import { formatDec, formatRa } from "../lib/mount.svelte";
  import { prefs } from "../lib/prefs.svelte";
  import {
    frameCorners,
    pan,
    project,
    scaleFor,
    screenAngle,
    separation,
    type Point,
    type Sky,
    type View,
    viewRadius,
    viewSpan,
  } from "../lib/sky/projection";
  import type { CameraField, CatalogObject, SkyChart } from "../lib/types";

  // The framing chart (ADR 0020): offline stars and deep-sky outlines around a
  // point, with the camera's frame fixed in the middle. The sky moves under the
  // frame: drag to pan, pinch or wheel to zoom, double tap to go back to the
  // target. `center` is where the frame points, J2000.
  let {
    target,
    center = $bindable({ ...target }),
    span = $bindable(4),
    field = null,
    rotation = 0,
    highlight = null,
  }: {
    // Where the chart opens and a double tap returns.
    target: Sky;
    center?: Sky;
    // Degrees across the chart's shorter side.
    span?: number;
    field?: CameraField | null;
    // Of the frame's top, degrees east of north (as a plate solution gives it).
    rotation?: number;
    // Id of the object to stand out (the target).
    highlight?: string | null;
  } = $props();

  const MIN_SPAN = 0.2;
  const MAX_SPAN = 70;
  // Stars asked for at once: enough for a 30° view to magnitude ~7.
  const LIMIT = 6000;
  const RAD = Math.PI / 180;

  let box: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let width = $state(0);
  let height = $state(0);

  const t = $derived(i18n.t);
  const view: View = $derived({ center, scale: scaleFor(span, width || 1, height || 1), width, height });
  // Fainter stars as the view narrows: magnitude 10 (the file's limit) below 1.5°.
  const magnitude = $derived(Math.max(5.5, Math.min(10, 10 - 2.2 * Math.log10(span / 1.5))));

  // -- Data -----------------------------------------------------------------------

  let chart: SkyChart | null = $state(null);
  let status: "loading" | "failed" | "ready" = $state("loading");
  let pending: ReturnType<typeof setTimeout> | undefined;
  let requested = 0;

  // What is loaded still covers the view: same stars or more, around it.
  function covers(data: SkyChart, radius: number): boolean {
    const off = separation(center, { ra: data.ra, dec: data.dec });
    const deepEnough = data.magnitude >= magnitude - 0.01 || (!data.truncated && data.magnitude >= 10);
    return off + radius <= data.radius && deepEnough && !(data.truncated && data.magnitude > magnitude + 1);
  }

  $effect(() => {
    if (width === 0 || height === 0) return;
    const radius = viewRadius(view);
    const data = untrack(() => chart);
    if (data && covers(data, radius)) return;
    clearTimeout(pending);
    // Ask for a margin around the view, so a short pan needs nothing new.
    const ask = { ...center, radius: Math.min(30, radius * 1.6), magnitude };
    pending = setTimeout(() => void load(ask), data ? 150 : 0);
  });

  async function load(ask: Sky & { radius: number; magnitude: number }): Promise<void> {
    const id = ++requested;
    if (!chart) status = "loading";
    try {
      // Rounded up, so what comes back covers the view's magnitude.
      const data = await getSkyChart(ask.ra, ask.dec, ask.radius, Math.ceil(ask.magnitude * 10) / 10, LIMIT);
      if (id !== requested) return;
      chart = data;
      status = "ready";
    } catch {
      if (id === requested && !chart) status = "failed";
    }
  }

  $effect(() => () => clearTimeout(pending));

  // -- Drawing --------------------------------------------------------------------

  type Palette = { bg: string; star: string; object: string; accent: string; line: string; text: string };

  function palette(): Palette {
    const style = getComputedStyle(document.documentElement);
    const token = (name: string) => style.getPropertyValue(name).trim();
    return {
      bg: token("--bg"),
      star: token("--text"),
      object: token("--muted"),
      accent: token("--accent"),
      line: token("--line"),
      text: token("--muted"),
    };
  }

  let colors: Palette | null = null;
  $effect(() => {
    void prefs.theme;
    colors = palette();
    schedule();
  });

  let frame = 0;
  // Coalesce redraws into one per animation frame.
  function schedule(): void {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      draw();
    });
  }

  $effect(() => {
    void [view, magnitude, chart, field, rotation, highlight];
    schedule();
  });

  $effect(() => () => cancelAnimationFrame(frame));

  function draw(): void {
    const context = canvas?.getContext("2d");
    if (!context || !colors || width === 0) return;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = colors.bg;
    context.fillRect(0, 0, width, height);
    const v = view;
    if (chart) {
      drawObjects(context, v, chart.objects, colors);
      drawStars(context, v, chart.stars, colors);
    }
    drawFrame(context, v, colors);
    drawCrosshair(context, colors);
  }

  function drawStars(context: CanvasRenderingContext2D, v: View, stars: number[][], palette: Palette): void {
    context.fillStyle = palette.star;
    context.beginPath();
    for (const [ra = 0, dec = 0, mag = 99] of stars) {
      // Brightest first: the rest are fainter than this view shows.
      if (mag > magnitude) break;
      const p = project(v, { ra, dec });
      if (!p || p.x < -8 || p.y < -8 || p.x > v.width + 8 || p.y > v.height + 8) continue;
      const r = Math.min(6, 0.7 + (magnitude - mag) * 0.55);
      context.moveTo(p.x + r, p.y);
      context.arc(p.x, p.y, r, 0, 2 * Math.PI);
    }
    context.fill();
  }

  const DASHED = new Set(["open_cluster", "dark_nebula", "asterism"]);

  function drawObjects(context: CanvasRenderingContext2D, v: View, objects: CatalogObject[], palette: Palette): void {
    context.font = "12px var(--font-sans), system-ui, sans-serif";
    context.textBaseline = "middle";
    // Pixels per degree at the centre: objects are small next to the view.
    const perDegree = v.scale * RAD;
    const shown: [CatalogObject, Point, number][] = [];
    for (const object of objects) {
      const p = project(v, object);
      const major = ((object.major_axis ?? 0) / 120) * perDegree;
      // Objects too small to outline show as a mark, only the brighter ones.
      if (major < 3 && object.id !== highlight && (object.magnitude ?? 99) > magnitude + 3) continue;
      if (!p || p.x < -major - 40 || p.y < -major - 40) continue;
      if (p.x > v.width + major + 40 || p.y > v.height + major + 40) continue;
      shown.push([object, p, major]);
    }
    // Labels only where they do not crowd the chart.
    const labelAll = shown.length <= 40;
    for (const [object, p, major] of shown) {
      const strong = object.id === highlight;
      context.strokeStyle = strong ? palette.accent : palette.object;
      context.lineWidth = strong ? 2 : 1.25;
      context.setLineDash(DASHED.has(object.type) ? [4, 3] : []);
      context.beginPath();
      if (major >= 3) {
        const minor = Math.max(1.5, ((object.minor_axis ?? object.major_axis ?? 0) / 120) * perDegree);
        const angle = screenAngle(v, object, object.position_angle ?? 0) ?? 0;
        context.ellipse(p.x, p.y, major, minor, angle, 0, 2 * Math.PI);
      } else {
        context.arc(p.x, p.y, 3, 0, 2 * Math.PI);
      }
      context.stroke();
      if (strong || labelAll || major >= 12) {
        context.fillStyle = strong ? palette.accent : palette.text;
        // Beside the outline, kept on screen for objects larger than the view.
        const text = context.measureText(object.label).width;
        const x = Math.min(p.x + Math.max(major, 3) * 0.75 + 4, v.width - text - 8);
        const y = Math.max(40, Math.min(p.y - Math.max(major, 3) * 0.5, v.height - 56));
        context.fillText(object.label, Math.max(8, x), y);
      }
    }
    context.setLineDash([]);
  }

  function drawFrame(context: CanvasRenderingContext2D, v: View, palette: Palette): void {
    if (!field) return;
    const corners = frameCorners(v, field.width, field.height, rotation);
    const [topLeft, topRight] = corners;
    if (!topLeft || !topRight) return;
    context.strokeStyle = palette.accent;
    context.fillStyle = palette.accent;
    context.lineWidth = 2;
    context.beginPath();
    corners.forEach((c, i) => (i === 0 ? context.moveTo(c.x, c.y) : context.lineTo(c.x, c.y)));
    context.closePath();
    context.stroke();
    // A notch on the top edge shows which way the frame's top points.
    const mid = { x: (topLeft.x + topRight.x) / 2, y: (topLeft.y + topRight.y) / 2 };
    const theta = rotation * RAD;
    const up = { x: -Math.sin(theta), y: -Math.cos(theta) };
    const side = { x: Math.cos(theta), y: -Math.sin(theta) };
    context.beginPath();
    context.moveTo(mid.x + up.x * 9, mid.y + up.y * 9);
    context.lineTo(mid.x + side.x * 6, mid.y + side.y * 6);
    context.lineTo(mid.x - side.x * 6, mid.y - side.y * 6);
    context.closePath();
    context.fill();
  }

  function drawCrosshair(context: CanvasRenderingContext2D, palette: Palette): void {
    const x = width / 2;
    const y = height / 2;
    context.strokeStyle = palette.object;
    context.lineWidth = 1;
    context.beginPath();
    for (const [dx, dy] of [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ] as const) {
      context.moveTo(x + dx * 5, y + dy * 5);
      context.lineTo(x + dx * 16, y + dy * 16);
    }
    context.stroke();
  }

  // -- Gestures -------------------------------------------------------------------

  function local(event: PointerEvent | WheelEvent | MouseEvent): Point {
    const rect = box.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function panBy(from: Point, to: Point): void {
    center = pan(view, from, to);
  }

  // Zoom keeping the sky under `at` (nearly) still.
  function zoomAt(next: number, at: Point): void {
    const clamped = Math.max(MIN_SPAN, Math.min(MAX_SPAN, next));
    if (clamped === span) return;
    const before = view;
    span = clamped;
    const after: View = { ...before, scale: scaleFor(clamped, width, height) };
    // The point under `at` moved towards (or away from) the centre: move it back.
    const middle = { x: width / 2, y: height / 2 };
    const ratio = after.scale / before.scale;
    const drifted = { x: middle.x + (at.x - middle.x) * ratio, y: middle.y + (at.y - middle.y) * ratio };
    center = pan(after, drifted, at);
  }

  function recenter(): void {
    center = { ...target };
  }

  const pointers = new Map<number, Point>();
  let moved = false;
  let lastTap = { time: 0, x: 0, y: 0 };

  function onpointerdown(event: PointerEvent): void {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    try {
      box.setPointerCapture(event.pointerId);
    } catch {
      // The pointer is already gone; its events simply stay with their target.
    }
    pointers.set(event.pointerId, local(event));
    if (pointers.size === 1) moved = false;
  }

  function onpointermove(event: PointerEvent): void {
    const previous = pointers.get(event.pointerId);
    if (!previous) return;
    const point = local(event);
    if (pointers.size === 1) {
      if (Math.hypot(point.x - previous.x, point.y - previous.y) > 0) panBy(previous, point);
      if (Math.hypot(point.x - previous.x, point.y - previous.y) > 4) moved = true;
    } else if (pointers.size === 2) {
      const other = [...pointers.entries()].find(([id]) => id !== event.pointerId)?.[1];
      if (other) {
        const before = Math.hypot(previous.x - other.x, previous.y - other.y);
        const after = Math.hypot(point.x - other.x, point.y - other.y);
        const middle = { x: (point.x + other.x) / 2, y: (point.y + other.y) / 2 };
        const previousMiddle = { x: (previous.x + other.x) / 2, y: (previous.y + other.y) / 2 };
        if (before > 0 && after > 0) zoomAt(span * (before / after), middle);
        panBy(previousMiddle, middle);
      }
      moved = true;
    }
    pointers.set(event.pointerId, point);
  }

  function onpointerup(event: PointerEvent): void {
    if (!pointers.delete(event.pointerId) || moved || pointers.size > 0) return;
    const point = local(event);
    const now = event.timeStamp;
    if (now - lastTap.time < 320 && Math.hypot(point.x - lastTap.x, point.y - lastTap.y) < 30) {
      recenter();
      lastTap = { time: 0, x: 0, y: 0 };
    } else {
      lastTap = { time: now, ...point };
    }
  }

  function onpointercancel(event: PointerEvent): void {
    pointers.delete(event.pointerId);
  }

  function onkeydown(event: KeyboardEvent): void {
    const middle = { x: width / 2, y: height / 2 };
    const step = Math.min(width, height) / 8;
    const moves: Record<string, Point> = {
      ArrowLeft: { x: middle.x + step, y: middle.y },
      ArrowRight: { x: middle.x - step, y: middle.y },
      ArrowUp: { x: middle.x, y: middle.y + step },
      ArrowDown: { x: middle.x, y: middle.y - step },
    };
    const to = moves[event.key];
    if (to) panBy(middle, to);
    else if (event.key === "+" || event.key === "=") zoomAt(span / 1.25, middle);
    else if (event.key === "-") zoomAt(span * 1.25, middle);
    else if (event.key === "0") recenter();
    else return;
    event.preventDefault();
  }

  // Wheel listeners must not be passive to keep the page from scrolling.
  $effect(() => {
    const onwheel = (event: WheelEvent) => {
      event.preventDefault();
      zoomAt(span * Math.exp(event.deltaY * 0.002), local(event));
    };
    box.addEventListener("wheel", onwheel, { passive: false });
    return () => box.removeEventListener("wheel", onwheel);
  });

  const frameText = $derived(
    field ? t.chart.frame(degrees(field.width), degrees(field.height), `${Math.round(((rotation % 360) + 360) % 360)}°`) : "",
  );

  function degrees(value: number): string {
    const digits = value < 1 ? 2 : value < 10 ? 1 : 0;
    return `${value.toLocaleString(i18n.locale, { maximumFractionDigits: digits, minimumFractionDigits: digits })}°`;
  }
</script>

<!-- An application region (ARIA) handles its own keys and gestures; Svelte's
     checks count it as non-interactive. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="chart"
  bind:this={box}
  bind:clientWidth={width}
  bind:clientHeight={height}
  role="application"
  aria-label={t.chart.label}
  tabindex="0"
  {onpointerdown}
  {onpointermove}
  {onpointerup}
  {onpointercancel}
  {onkeydown}>
  <canvas bind:this={canvas}></canvas>
  <div class="top">
    {#if status === "loading"}<span>{t.chart.loading}</span>
    {:else if status === "failed"}<span class="error">{t.chart.failed}</span>
    {:else if chart && !chart.star_catalog}<span>{t.chart.noStars}</span>{/if}
  </div>
  <div class="readout">
    <span class="mono">{formatRa(center.ra)} {formatDec(center.dec)}</span>
    <span>{field ? `${frameText} · ` : ""}{t.chart.view(degrees(viewSpan(view)))}</span>
  </div>
  <div class="credit">{t.chart.credit}</div>
</div>

<style>
  .chart {
    position: relative;
    overflow: hidden;
    width: 100%;
    height: 100%;
    background: var(--bg);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    outline: none;
  }
  .chart:focus-visible {
    box-shadow: inset 0 0 0 2px var(--accent);
  }
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .top,
  .readout,
  .credit {
    position: absolute;
    pointer-events: none;
    color: var(--muted);
    font-size: 12px;
    line-height: 16px;
  }
  .top {
    top: var(--space-2);
    left: var(--space-3);
  }
  .error {
    color: var(--error);
  }
  .readout {
    left: var(--space-3);
    bottom: var(--space-2);
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: var(--text);
    text-shadow: 0 0 3px var(--bg);
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 18px;
  }
  .credit {
    right: var(--space-3);
    top: var(--space-2);
    font-size: 11px;
  }
</style>
