<script lang="ts">
  import { type Snippet, untrack } from "svelte";
  import { prefs } from "../../lib/prefs.svelte";

  // The preview image with pinch / wheel zoom, drag to pan and double tap to
  // switch between fitting the frame and its pixels at full size. It is drawn
  // on a canvas so Night mode can map it to red only (docs/ux.md §3): never
  // white stars, whatever the image holds. The zoom survives new frames of the
  // same size, which is what focusing needs.
  let {
    url,
    width,
    height,
    label,
    empty,
    children,
  }: {
    url: string | null;
    width: number;
    height: number;
    // Accessible description of the image.
    label: string;
    // Shown while there is no image.
    empty?: Snippet;
    // Overlays (readouts, buttons) on top of the image.
    children?: Snippet;
  } = $props();

  let box: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let boxWidth = $state(0);
  let boxHeight = $state(0);
  let shown = $state(false);
  // Zoom relative to fitting the box, and pan in CSS pixels from the center.
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);

  const night = $derived(prefs.theme === "night");
  const fit = $derived(width > 0 && height > 0 && boxWidth > 0 ? Math.min(boxWidth / width, boxHeight / height) : 1);
  // At most four screen pixels per image pixel.
  const maxZoom = $derived(Math.max(2, 4 / fit));
  const pixelated = $derived(zoom * fit > 1.5);

  // A frame of another size (binning, region, the other camera): start over.
  $effect(() => {
    void [width, height];
    zoom = 1;
    panX = 0;
    panY = 0;
  });

  // Draw each image once loaded, so the previous frame stays until the next one
  // is ready. Loads are never cancelled: when a phone is slow to load frames
  // that come every two seconds, the newest one that arrives is drawn.
  let requested = 0;
  let drawn = 0;
  let image: HTMLImageElement | null = null;

  $effect(() => {
    const source = url;
    if (!source) {
      shown = false;
      return;
    }
    const id = ++requested;
    const loading = new Image();
    loading.onload = () => {
      if (id <= drawn) return;
      drawn = id;
      image = loading;
      draw(loading, untrack(() => night));
      shown = true;
    };
    // A preview that cannot be loaded (replaced, server gone): keep the last one.
    loading.src = source;
  });

  // The theme changed: draw the same image again.
  $effect(() => {
    const red = night;
    if (image) draw(image, red);
  });

  function draw(image: HTMLImageElement, red: boolean): void {
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    context.drawImage(image, 0, 0);
    if (!red) return;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    const data = pixels.data;
    // Luminance into the red channel only, slightly dimmed.
    for (let i = 0; i < data.length; i += 4) {
      data[i] = 0.18 * (data[i] ?? 0) + 0.6 * (data[i + 1] ?? 0) + 0.07 * (data[i + 2] ?? 0);
      data[i + 1] = 0;
      data[i + 2] = 0;
    }
    context.putImageData(pixels, 0, 0);
  }

  // -- Gestures -------------------------------------------------------------------

  type Point = { x: number; y: number };

  function clampPan(x: number, y: number, z = zoom): Point {
    const spareX = Math.max(0, (width * fit * z - boxWidth) / 2);
    const spareY = Math.max(0, (height * fit * z - boxHeight) / 2);
    return { x: Math.min(spareX, Math.max(-spareX, x)), y: Math.min(spareY, Math.max(-spareY, y)) };
  }

  // Zoom keeping the image point under `at` (relative to the box center) still.
  function zoomAt(next: number, at: Point): void {
    const z = Math.min(maxZoom, Math.max(1, next));
    const ratio = z / zoom;
    const pan = clampPan(at.x - (at.x - panX) * ratio, at.y - (at.y - panY) * ratio, z);
    zoom = z;
    panX = pan.x;
    panY = pan.y;
  }

  function panBy(dx: number, dy: number): void {
    const pan = clampPan(panX + dx, panY + dy);
    panX = pan.x;
    panY = pan.y;
  }

  function local(event: PointerEvent | WheelEvent): Point {
    const rect = box.getBoundingClientRect();
    return { x: event.clientX - rect.left - rect.width / 2, y: event.clientY - rect.top - rect.height / 2 };
  }

  const pointers = new Map<number, Point>();
  let moved = false;
  let lastTap = { time: 0, x: 0, y: 0 };

  function toggleZoom(at: Point): void {
    if (zoom > 1.01) {
      zoom = 1;
      panX = 0;
      panY = 0;
    } else {
      zoomAt(Math.max(2, 1 / fit), at);
    }
  }

  function onpointerdown(event: PointerEvent): void {
    if (!shown || (event.pointerType === "mouse" && event.button !== 0)) return;
    // Overlay buttons handle their own taps.
    if (event.target instanceof Element && event.target.closest("button, a")) return;
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
      const dx = point.x - previous.x;
      const dy = point.y - previous.y;
      if (Math.hypot(dx, dy) > 0) panBy(dx, dy);
      if (Math.hypot(dx, dy) > 4) moved = true;
    } else if (pointers.size === 2) {
      const other = [...pointers.entries()].find(([id]) => id !== event.pointerId)?.[1];
      if (other) {
        const before = Math.hypot(previous.x - other.x, previous.y - other.y);
        const after = Math.hypot(point.x - other.x, point.y - other.y);
        const middle = { x: (point.x + other.x) / 2, y: (point.y + other.y) / 2 };
        if (before > 0) zoomAt(zoom * (after / before), middle);
        panBy((point.x - previous.x) / 2, (point.y - previous.y) / 2);
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
      toggleZoom(point);
      lastTap = { time: 0, x: 0, y: 0 };
    } else {
      lastTap = { time: now, ...point };
    }
  }

  function onpointercancel(event: PointerEvent): void {
    pointers.delete(event.pointerId);
  }

  // Wheel listeners must not be passive to keep the page from scrolling.
  $effect(() => {
    const onwheel = (event: WheelEvent) => {
      if (!shown) return;
      event.preventDefault();
      zoomAt(zoom * Math.exp(-event.deltaY * 0.002), local(event));
    };
    box.addEventListener("wheel", onwheel, { passive: false });
    return () => box.removeEventListener("wheel", onwheel);
  });
</script>

<div
  class="viewer"
  bind:this={box}
  bind:clientWidth={boxWidth}
  bind:clientHeight={boxHeight}
  role="presentation"
  {onpointerdown}
  {onpointermove}
  {onpointerup}
  {onpointercancel}>
  <canvas
    bind:this={canvas}
    class:hidden={!shown || !url}
    class:pixelated
    style:width="{width * fit}px"
    style:height="{height * fit}px"
    style:transform="translate(-50%, -50%) translate({panX}px, {panY}px) scale({zoom})">{label}</canvas>
  {#if !url && empty}<div class="empty">{@render empty()}</div>{/if}
  {@render children?.()}
</div>

<style>
  .viewer {
    position: relative;
    overflow: hidden;
    width: 100%;
    height: 100%;
    background: #000;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  canvas {
    position: absolute;
    left: 50%;
    top: 50%;
    transform-origin: center;
  }
  .hidden {
    visibility: hidden;
  }
  .pixelated {
    image-rendering: pixelated;
  }
  .empty {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    padding: var(--space-12) var(--margin);
    text-align: center;
  }
</style>
