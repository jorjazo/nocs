<script lang="ts">
  // Video: lucky imaging of the Moon, the Sun and the planets. The main camera streams
  // live, as fast as it reads, and its driver records SER files of it to the storage
  // destination (thousands of short frames, stacked later on a computer). The image
  // fills the screen as in Explore, linear (as recorded), with the histogram and the
  // status bar under it, the focuser (by hand, on a sharpness number) and the go to
  // over it, and the panel of settings at its side: exposure, gain, depth, the region
  // read out, the filter, the mount's tracking rate, and the recording's length.
  // A recording keeps the mount, the focuser and the wheel still until it ends.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import ImageScreen from "../../components/ImageScreen.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Tile from "../../components/Tile.svelte";
  import {
    recordVideo,
    selectFilter,
    setTracking,
    setVideoSettings,
    startVideo,
    stopRecording,
    stopVideo,
  } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder, slotLabel } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { exploreLayout } from "../../lib/explore.svelte";
  import { formatBytes, formatDecimal, formatPlain, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { Region } from "../../lib/types";
  import {
    frameBytes,
    type Length,
    recordingBytes,
    regionAt,
    type RegionSize,
    regionSizes,
    sameSize,
    sensorPoint,
  } from "../../lib/video";
  import { VideoFrames } from "../../lib/videoframes.svelte";
  import FilterWheelSheet from "../devices/FilterWheelSheet.svelte";
  import FocuserSheet from "../devices/FocuserSheet.svelte";
  import FocusTool from "../explore/FocusTool.svelte";
  import FrameStatus from "../explore/FrameStatus.svelte";
  import GoToTool from "../explore/GoToTool.svelte";
  import ImageOverlay from "../explore/ImageOverlay.svelte";
  import Shutter from "../explore/Shutter.svelte";
  import Viewer from "../explore/Viewer.svelte";
  import Recordings from "./Recordings.svelte";
  import VideoHistogram from "./VideoHistogram.svelte";
  import VideoSheet from "./VideoSheet.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);

  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const video = $derived(live.app.video ?? null);
  const frame = $derived(video?.frame ?? null);
  const recording = $derived(video?.recording ?? null);
  const streaming = $derived(!!video?.streaming);
  const starting = $derived(!!video?.job && !streaming);
  const mount = $derived(live.app.mount ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const wheel = $derived(live.app.filter_wheel ?? null);

  // The main camera at work elsewhere (Explore's loop, autofocus…): Video waits.
  const cameraJob = $derived(holder(live.app.jobs, "main_camera"));
  const busyElsewhere = $derived(cameraJob !== null && cameraJob.info.kind !== "video");
  const wheelJob = $derived(holder(live.app.jobs, "filter_wheel"));
  const focuserJob = $derived(holder(live.app.jobs, "focuser"));

  // -- The previews ----------------------------------------------------------------

  const frames = new VideoFrames();
  $effect(() => frames.run(streaming));
  $effect(() => frames.resync(frame?.seq ?? null));
  $effect(() => () => frames.close());

  // The sharpest frame since the image last changed (exposure, gain, region): focus
  // by hand until the number stops growing.
  let best = $state<number | null>(null);
  let bestKey = "";
  $effect(() => {
    const key = JSON.stringify([video?.exposure, video?.gain, video?.region, video?.depth, streaming]);
    const now = frame?.sharpness ?? null;
    if (key !== bestKey) {
      bestKey = key;
      best = now;
    } else if (now !== null && (best === null || now > best)) {
      best = now;
    }
  });

  // -- Actions ---------------------------------------------------------------------

  let busy = $state(false);
  let actionError = $state("");

  async function act(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    actionError = "";
    try {
      await action();
    } catch (e) {
      actionError = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  function toggleStream(): void {
    void act(() => (video?.job ? stopVideo() : startVideo()));
  }

  // -- Settings --------------------------------------------------------------------

  const locked = $derived(!owner || recording !== null);
  let editing = $state<"exposure" | "gain" | null>(null);
  let device = $state<"focuser" | "filter_wheel" | null>(null);

  const sensor = $derived(camera ? { width: camera.sensor.width, height: camera.sensor.height } : null);
  const sizes = $derived(sensor ? regionSizes(sensor) : []);
  const region = $derived(video?.region ?? null);
  // The size chosen for the region: the one read out, else the last one picked here.
  let picked = $state<RegionSize | null>(null);
  const size = $derived(region ? { width: region.width, height: region.height } : picked);
  const sizeValue = $derived(region ? `${region.width}x${region.height}` : "full");
  let placing = $state(false);

  function setRegion(value: string): void {
    if (!sensor) return;
    if (value === "full") {
      picked = null;
      placing = false;
      void act(() => setVideoSettings({ region: "full" }));
      return;
    }
    const chosen = sizes.find((s) => `${s.width}x${s.height}` === value);
    if (!chosen) return;
    picked = chosen;
    // Where the region is now, or the sensor's centre.
    const centre = region
      ? { x: region.x + region.width / 2, y: region.y + region.height / 2 }
      : { x: sensor.width / 2, y: sensor.height / 2 };
    void act(() => setVideoSettings({ region: regionAt(centre.x, centre.y, chosen, sensor) }));
  }

  // Placing the region: a tap on the image centres it there. Otherwise a tap shows
  // or hides what lies over the image, as in Explore.
  function tapped(at: { x: number; y: number } | null): void {
    if (!placing || !sensor) {
      exploreLayout.toggleOverlays();
      return;
    }
    if (!at) return;
    placing = false;
    const target: RegionSize = size ?? sizes[1] ?? sizes[0] ?? { width: 640, height: 480 };
    const point = sensorPoint(at, region, sensor);
    const next: Region = regionAt(point.x, point.y, target, sensor);
    void act(() => setVideoSettings({ region: next }));
  }

  const depths = $derived(camera?.video?.depths ?? []);

  // -- Tracking -------------------------------------------------------------------

  const trackModes = $derived(mount?.track_modes ?? []);

  // -- Recording ------------------------------------------------------------------

  let mode = $state<Length["mode"]>("seconds");
  let seconds = $state<number | null>(60);
  let count = $state<number | null>(5000);
  const length = $derived<Length | null>(
    mode === "seconds" ? (seconds ? { mode, value: seconds } : null) : count ? { mode, value: count } : null,
  );
  const estimate = $derived.by(() => {
    if (!frame || !length) return null;
    const bytes = frameBytes(frame.frame_width, frame.frame_height, frame.depth);
    return recordingBytes(length, bytes, video?.fps ?? null);
  });
  const destination = $derived.by(() => {
    const storage = live.app.storage;
    return storage?.destinations.find((d) => d.id === storage.destination) ?? null;
  });
  const fat = $derived(destination ? ["vfat", "msdos", "fat"].includes(destination.fs) : false);

  const recordReason = $derived.by((): string | null => {
    if (!owner) return t.video.ownerOnly;
    if (!streaming) return t.video.needsStream;
    if (!length) return t.live.invalid;
    return null;
  });

  function record(): void {
    void act(async () => {
      if (recording) {
        await stopRecording();
        return;
      }
      if (!length) return;
      await recordVideo(length.mode === "seconds" ? { seconds: length.value } : { frames: length.value });
    });
  }

  const recordProgress = $derived.by(() => {
    if (!recording) return null;
    if (recording.frames) return recording.written / recording.frames;
    if (recording.seconds) {
      const elapsed = (Date.now() - Date.parse(recording.started)) / 1000;
      return Math.min(1, elapsed / recording.seconds);
    }
    return null;
  });

  // -- Status -----------------------------------------------------------------------

  const status = $derived.by((): { tone: Tone; text: string } | null => {
    if (recording) {
      const text = recording.stopping
        ? t.video.stopping[recording.stopping]
        : `${t.video.status.recording} · ${t.video.recording(formatPlain(recording.written, locale), formatBytes(recording.size, locale))}`;
      return { tone: recording.stopping ? "warning" : "accent", text };
    }
    // The driver can say it streams while the camera sends nothing.
    if (streaming) return { tone: "accent", text: frame ? t.video.status.streaming : t.video.status.waiting };
    if (starting) return { tone: "accent", text: t.video.status.starting };
    if (video?.error) return { tone: "error", text: t.video.failed };
    return { tone: "neutral", text: t.video.status.idle };
  });

  const items = $derived.by((): string[] => {
    if (!frame || !video) return [];
    const parts = [
      t.live.statusBar.size(frame.frame_width, frame.frame_height),
      t.video.bits(frame.depth),
      `${formatPlain(video.exposure * 1000, locale)} ms`,
    ];
    if (video.fps !== null) parts.push(t.video.fps(formatDecimal(video.fps, locale, 1)));
    parts.push(`${t.video.sharpness} ${formatDecimal(frame.sharpness, locale, 1)}`);
    return parts;
  });

  const longitude = $derived.by(() => {
    const sites = live.app.sites;
    const site = sites?.active ? sites.saved[sites.active] : null;
    return site?.longitude ?? mount?.site?.longitude ?? null;
  });

  // -- Layout ----------------------------------------------------------------------

  let expanded = $state(false);
  const portrait = $derived(exploreLayout.orientation === "portrait");
  const overlays = $derived(exploreLayout.overlays);
  const sheetOpen = $derived(portrait && exploreLayout.open("panel"));
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && expanded && !document.querySelector("dialog[open]")) expanded = false;
  }} />

<h1 class="visually-hidden">{t.video.title}</h1>

{#if !camera}
  <div class="padded">
    <EmptyState icon="video" title={t.video.noCamera} body={t.video.noCameraBody}>
      {#snippet action()}
        <Button variant="primary" onclick={() => router.go({ screen: "rig" })}>{t.empty.openRig}</Button>
      {/snippet}
    </EmptyState>
  </div>
{:else if !camera.video}
  <div class="padded">
    <EmptyState icon="video" title={t.video.title} body={t.video.cannotStream} />
  </div>
{:else}
  <ImageScreen
    {portrait}
    {expanded}
    {sheetOpen}
    stageLabel={t.video.preview}
    panelLabel={t.video.controls}
    openLabel={t.live.panelOpen}
    closeLabel={t.live.panelClose}
    ontogglesheet={() => exploreLayout.toggle("panel")}>
    {#snippet image()}
      <Viewer
        url={frames.url}
        width={frame?.width ?? 0}
        height={frame?.height ?? 0}
        label={t.video.previewLabel(camera.device)}
        ontap={tapped}>
        {#snippet empty()}
          <div class="nopreview">
            <p class="heading">{streaming ? t.video.waiting : t.video.noPreview}</p>
            <p class="muted">{streaming ? t.video.waitingBody : t.video.noPreviewBody}</p>
          </div>
        {/snippet}
        <ImageOverlay
          {portrait}
          {overlays}
          {expanded}
          wide={exploreLayout.open("goto")}
          ontoggleoverlays={() => exploreLayout.toggleOverlays()}
          ontoggleexpanded={() => (expanded = !expanded)}>
          {#snippet tools()}
            {#if focuser}
              <FocusTool
                {focuser}
                autofocus={null}
                autofocusable={false}
                {owner}
                locked={recording !== null || (focuserJob !== null && focuserJob.info.kind !== "focus")}
                cameraBusy={false}
                open={exploreLayout.open("focus")}
                ontoggle={() => exploreLayout.toggle("focus")}
                onsheet={() => (device = "focuser")}
                run={act}>
                {#if frame}
                  <div class="sharpness" title={t.video.sharpnessHint}>
                    <span class="caption muted">{t.video.sharpness}</span>
                    <span class="mono value">{formatDecimal(frame.sharpness, locale, 1)}</span>
                    {#if best !== null}
                      <span class="caption muted">{t.video.sharpnessBest(formatDecimal(best, locale, 1))}</span>
                    {/if}
                  </div>
                {/if}
              </FocusTool>
            {/if}
          {/snippet}
          {#snippet side()}
            {#if mount}
              <GoToTool
                {mount}
                {owner}
                held={recording ? t.video.recordingHolds : null}
                open={exploreLayout.open("goto")}
                ontoggle={() => exploreLayout.toggle("goto")} />
            {/if}
          {/snippet}
        </ImageOverlay>
      </Viewer>
    {/snippet}
    {#snippet under()}
      {#if overlays}
        <VideoHistogram {frame} open={exploreLayout.open("histogram")} ontoggle={() => exploreLayout.toggle("histogram")} />
      {/if}
      <FrameStatus {camera} preview={null} {status} {mount} {longitude} {items} />
    {/snippet}
    {#snippet body()}
      {#if busyElsewhere}<Banner icon="alert" tone="warning">{t.video.cameraBusy}</Banner>{/if}

      <div class="tiles">
        <Tile
          label={t.video.exposure}
          value="{formatPlain((video?.exposure ?? 0) * 1000, locale)} ms"
          disabled={locked || !video}
          onclick={() => (editing = "exposure")} />
        <Tile
          label={t.video.gain}
          value={video?.gain != null ? formatPlain(video.gain, locale) : camera.gain === null ? "—" : formatPlain(camera.gain, locale)}
          detail={video?.gain == null ? t.video.gainCamera : undefined}
          disabled={locked || !camera.gain_range || !video}
          onclick={() => (editing = "gain")} />
        <Tile
          label={t.live.cooler}
          value={camera.temperature === null ? "—" : formatTemperature(camera.temperature, locale)}
          detail={camera.target !== null ? formatTemperature(camera.target, locale, 0) : undefined}
          disabled
          onclick={() => {}} />
      </div>

      {#if depths.length > 1}
        <SegmentedControl
          label={t.video.depth}
          options={depths.map((bits) => ({ value: String(bits), label: t.video.bits(bits) }))}
          value={String(video?.depth ?? depths[0])}
          disabled={locked}
          onchange={(value) => void act(() => setVideoSettings({ depth: Number(value) as 8 | 16 }))} />
        <p class="caption muted hint">{t.video.depthHint}</p>
      {/if}

      {#if sizes.length > 0}
        <div class="group">
          <SegmentedControl
            label={t.video.region}
            options={[
              { value: "full", label: t.video.full },
              ...sizes.map((s) => ({ value: `${s.width}x${s.height}`, label: t.video.size(s.width, s.height) })),
            ]}
            value={sizes.some((s) => sameSize(region, s)) || !region ? sizeValue : "full"}
            disabled={locked}
            onchange={setRegion} />
          <div class="row">
            <Button variant="text" disabled={locked || !frame} onclick={() => (placing = !placing)}>
              <Icon name="focus" size={18} />
              {t.video.place}
            </Button>
          </div>
          <p class="caption muted hint" role="status">{placing ? t.video.placing : t.video.regionHint}</p>
        </div>
      {/if}

      {#if wheel}
        <SegmentedControl
          label={t.live.filter}
          options={Array.from({ length: wheel.slots }, (_, i) => ({ value: String(i + 1), label: slotLabel(wheel, i + 1, t) }))}
          value={String(wheel.slot ?? "")}
          disabled={locked || (wheelJob !== null && wheelJob.info.kind !== "filter") || wheel.moving}
          onchange={(value) => void act(() => selectFilter({ slot: Number(value) }))} />
      {/if}

      {#if mount && trackModes.length > 1 && mount.track_mode}
        <SegmentedControl
          label={t.video.tracking}
          options={trackModes.map((value) => ({ value, label: t.mount.modes[value] ?? value }))}
          value={mount.track_mode}
          disabled={locked}
          onchange={(value) => void act(() => setTracking({ mode: value }))} />
      {/if}

      <div class="group">
        <SegmentedControl
          label={t.video.length}
          options={[
            { value: "seconds", label: t.video.seconds },
            { value: "frames", label: t.video.frames },
          ]}
          value={mode}
          disabled={recording !== null}
          onchange={(value) => (mode = value as Length["mode"])} />
        {#if mode === "seconds"}
          <Stepper label={t.video.seconds} bind:value={seconds} min={1} max={3600} unit="s" disabled={recording !== null} />
        {:else}
          <Stepper label={t.video.frames} bind:value={count} min={1} max={1000000} step={100} disabled={recording !== null} />
        {/if}
        {#if estimate !== null}
          <p class="caption muted">{t.video.estimate(formatBytes(estimate, locale))}</p>
        {/if}
        {#if fat}<p class="caption muted">{t.video.fatLimit}</p>{/if}
      </div>

      {#if recording && owner}<p class="caption muted">{t.video.locked}</p>{/if}

      {#if video}
        <Recordings recordings={video.recordings} {owner} run={act} />
      {/if}
    {/snippet}
    {#snippet dock()}
      {#if actionError}
        <Banner icon="alert" tone="error">
          {actionError}
          {#snippet action()}
            <Button variant="text" onclick={() => (actionError = "")}>{t.live.dismiss}</Button>
          {/snippet}
        </Banner>
      {/if}
      {#if video?.error && !video.job}
        <Banner icon="alert" tone="error">{t.video.failed}: {video.error}</Banner>
      {/if}
      <div class="actions">
        <button
          type="button"
          class="action"
          class:on={!!video?.job}
          aria-pressed={!!video?.job}
          disabled={!owner || busy || busyElsewhere || recording !== null}
          onclick={toggleStream}>
          <Icon name={video?.job ? "stop" : "video"} />
          {video?.job ? t.video.stop : t.video.start}
        </button>
        <Shutter
          running={recording !== null}
          progress={recordProgress}
          label={recording ? t.video.recordStop : t.video.record}
          disabled={busy || (recording === null && recordReason !== null)}
          onclick={record} />
        <span class="action placeholder" aria-hidden="true"></span>
      </div>
      <p class="caption muted outcome" aria-live="polite">
        {#if recording}
          {recording.destination_label}: {recording.path}
        {:else if recordReason && owner}
          {recordReason}
        {/if}
      </p>
    {/snippet}
  </ImageScreen>

  {#if editing && video}
    <VideoSheet setting={editing} {video} {camera} onclose={() => (editing = null)} />
  {/if}
  {#if device === "focuser"}
    <FocuserSheet onclose={() => (device = null)} />
  {:else if device === "filter_wheel"}
    <FilterWheelSheet onclose={() => (device = null)} />
  {/if}
{/if}

<style>
  .padded {
    padding: 0 var(--margin);
  }
  .nopreview {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .row {
    display: flex;
    gap: var(--space-2);
  }
  .hint {
    margin: calc(-1 * var(--space-1)) 0 0;
  }
  .sharpness {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
  }
  .value {
    font-size: 20px;
    font-weight: 600;
  }
  .actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-3);
  }
  .action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-width: 0;
    min-height: var(--primary-height);
    padding: 0 var(--space-2);
    overflow: hidden;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
  }
  .action:disabled {
    cursor: default;
    opacity: 0.55;
  }
  .action.on {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) var(--tint), var(--surface));
    color: var(--accent);
  }
  .placeholder {
    visibility: hidden;
  }
  .outcome {
    min-height: 16px;
    text-align: center;
    overflow-wrap: anywhere;
  }
  p {
    margin: 0;
  }
</style>
