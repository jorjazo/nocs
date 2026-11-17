<script lang="ts">
  // Explore (ADR 0054): look at the sky tonight and try things with it, the framing,
  // the exposure, the colours. The latest image fills the screen, with the
  // histogram and the status bar under it and the tools over it; the panel of
  // actions sits at its side, or in a sheet over it when the screen stands upright.
  // Settings, the exposure time included, are kept by the server and shared by every
  // client; how the screen is laid out belongs to this device.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Tile from "../../components/Tile.svelte";
  import { cancelJob, expose, loop, saveShown, saveStack, selectFilter, setCameraSettings, solve } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import {
    CAMERA_ROLES,
    type CameraJob,
    cameraJobs,
    capture,
    holder,
    MAX_LOOP_EXPOSURE,
    MAX_SERIES,
    slotLabel,
  } from "../../lib/camera.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import FilterWheelSheet from "../devices/FilterWheelSheet.svelte";
  import FocuserSheet from "../devices/FocuserSheet.svelte";
  import FocusTool from "./FocusTool.svelte";
  import GoToTool from "./GoToTool.svelte";
  import FrameStatus from "./FrameStatus.svelte";
  import GuidingTool from "./GuidingTool.svelte";
  import HistogramBar from "./HistogramBar.svelte";
  import PillSwitch from "../../components/PillSwitch.svelte";
  import { exploreLayout } from "../../lib/explore.svelte";
  import { solvedShown } from "../../lib/explore";
  import SettingSheet, { type Setting } from "./SettingSheet.svelte";
  import Shutter from "./Shutter.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import { solveExposure } from "../../lib/equipment";
  import StackCard from "./StackCard.svelte";
  import Viewer from "./Viewer.svelte";
  import { stackView } from "../../lib/stackview.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const cameras = $derived(live.app.cameras ?? {});
  const available = $derived(CAMERA_ROLES.filter((role) => cameras[role]));
  const role = $derived(available.includes(capture.role) ? capture.role : (available[0] ?? "main_camera"));
  const camera = $derived(cameras[role] ?? null);
  const preview = $derived(camera?.preview ?? null);
  const owner = $derived(auth.owner);
  // While PHD2 has the guide camera, it is PHD2's: its frames show here (ADR 0023).
  const inUse = $derived(camera?.used_by === "phd2");
  const guiding = $derived(live.app.guiding ?? null);

  // Only the main camera saves frames, and only it gets the filter and the
  // focuser (ADR 0013). A main camera exposure locks both; a loop does not, so
  // focusing and trying filters work while looping.
  const main = $derived(role === "main_camera");
  const wheel = $derived(main ? (live.app.filter_wheel ?? null) : null);
  const focuser = $derived(main ? (live.app.focuser ?? null) : null);
  const filterName = $derived(wheel?.slot ? slotLabel(wheel, wheel.slot, t) : null);
  const wheelJob = $derived(holder(live.app.jobs, "filter_wheel"));
  const focuserJob = $derived(holder(live.app.jobs, "focuser"));
  const wheelLocked = $derived(wheelJob !== null && wheelJob.info.kind !== "filter");
  const focuserLocked = $derived(focuserJob !== null && focuserJob.info.kind !== "focus");

  // -- Jobs -------------------------------------------------------------------------

  const jobs = $derived(cameraJobs(live.app.jobs, role));
  // A sequence's job is never this screen's to cancel: SequenceHold offers a pause.
  const running = $derived(jobs.running?.info.kind === "sequence" ? null : jobs.running);
  const looping = $derived(running?.info.kind === "loop");
  // The server records the exposure a job uses, and refuses changes while it runs.
  const exposure = $derived(camera?.exposure ?? null);
  const remaining = $derived(camera?.exposing ? camera.remaining : null);
  const total = $derived(running ? exposure : null);
  const progress = $derived.by(() => {
    if (!running || remaining === null) return null;
    if (total) return 1 - remaining / total;
    return running.info.progress;
  });

  let dismissed = $state<string | null>(null);
  // Only this screen's own jobs: workflows that use the camera report their
  // failures where they are shown (autofocus on its screen, the finder in its card).
  // Solving the frame on screen holds no device, so it is not among the camera's jobs.
  const solveJob = $derived.by((): CameraJob | null => {
    let latest: CameraJob | null = null;
    for (const [id, info] of Object.entries(live.app.jobs ?? {})) {
      if (info.kind === "solve" && (!latest || info.started > latest.info.started)) latest = { id, info };
    }
    return latest;
  });
  const failed = $derived.by((): CameraJob | null => {
    const own = jobs.latest;
    const candidates = [
      own && (own.info.kind === "expose" || own.info.kind === "loop") ? own : null,
      main ? solveJob : null,
    ].filter((job): job is CameraJob => job !== null && job.info.state === "failed" && job.id !== dismissed);
    return candidates.sort((a, b) => b.info.started.localeCompare(a.info.started))[0] ?? null;
  });
  // A failed solve, explained when the solver says why.
  const failure = $derived.by((): string | null => {
    if (!failed) return null;
    const why = live.app.solver?.failure;
    if (failed.info.kind === "solve" && why && why.message === failed.info.error) {
      return why.reason === "error" ? `${t.solve.failures.error} ${why.message}` : t.solve.failures[why.reason];
    }
    return failed.info.error ?? t.live.status.failed;
  });

  // "frame 3/10: …" from a series' job, as "3/10 · ".
  const seriesPrefix = $derived.by(() => {
    const match = running?.info.message?.match(/^frame (\d+)\/(\d+): /);
    return match ? `${match[1]}/${match[2]} · ` : "";
  });
  const status = $derived.by((): { tone: Tone; text: string } | null => {
    const plain = seriesStatus();
    return plain ? { tone: plain.tone, text: seriesPrefix + plain.text } : null;
  });

  function seriesStatus(): { tone: Tone; text: string } | null {
    if (inUse) return { tone: "accent", text: guiding?.app_state ? t.guiding.state[guiding.app_state] : t.guiding.unknown };
    if (running) {
      if (running.info.message?.includes("dither")) return { tone: "accent", text: t.guiding.dithering };
      if (remaining !== null) {
        const left = formatPlain(Math.ceil(remaining), locale);
        if (looping) return { tone: "accent", text: t.live.status.loopLeft(left) };
        if (total) {
          const elapsed = formatPlain(Math.max(0, Math.floor(total - remaining)), locale);
          return { tone: "accent", text: t.live.status.exposing(elapsed, formatPlain(total, locale)) };
        }
        return { tone: "accent", text: t.live.status.left(left) };
      }
      if (running.info.kind === "solve") return { tone: "accent", text: t.live.status.solving };
      if (running.info.kind === "center") return { tone: "accent", text: t.live.status.centering };
      if (running.info.kind === "find") return { tone: "accent", text: t.finder.title };
      return { tone: "accent", text: looping ? t.live.status.looping : t.live.status.processing };
    }
    if (solving) return { tone: "accent", text: t.live.status.solving };
    if (failed) return { tone: "error", text: t.live.status.failed };
    return null;
  }

  // -- Actions -------------------------------------------------------------------------

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

  function shoot(): void {
    void act(async () => {
      if (running) {
        await cancelJob(running.id);
        return;
      }
      if (exposure === null) return;
      // Explore takes lights and keeps nothing at the time: Save keeps what is on screen.
      await expose(role, exposure, main ? { save: false, count: capture.count, light: true } : {});
    });
  }

  function toggleLoop(): void {
    void act(async () => {
      if (running) {
        await cancelJob(running.id);
        return;
      }
      if (exposure === null) return;
      if (exposure > MAX_LOOP_EXPOSURE) {
        throw new Error(t.live.loopMax(formatSeconds(MAX_LOOP_EXPOSURE, locale)));
      }
      await loop(role, exposure, main);
    });
  }

  function pickFilter(value: string): void {
    void act(() => selectFilter({ slot: Number(value) }));
  }

  // -- Layout ----------------------------------------------------------------------------

  let editing = $state<Setting | null>(null);
  let device = $state<"focuser" | "filter_wheel" | null>(null);

  // The mount, framed by hand with the go to panel's pad: while it is open the image's
  // centre is marked, and while the mount moves the newest frame shows.
  const mount = $derived(live.app.mount ?? null);
  const framing = $derived(mount !== null && exploreLayout.overlays && exploreLayout.open("goto"));
  const moving = $derived(!!mount && (mount.slewing || mount.moving.ns !== null || mount.moving.we !== null));
  // The live stack replaces the frame in the viewer while it has one, unless this
  // device chose to watch the frames (ADR 0040).
  const stack = $derived(live.app.stack ?? null);
  // While the mount moves, the newest frame shows whatever the choice: the stack
  // cannot show where the mount points now.
  const stacked = $derived(
    role === "main_camera" && stack?.on && stackView.view === "stack" && !moving
      ? (stack.current ?? null)
      : null,
  );
  const shown = $derived(stacked?.preview ?? preview);
  let expanded = $state(false);
  const portrait = $derived(exploreLayout.orientation === "portrait");
  const overlays = $derived(exploreLayout.overlays);
  const sheetOpen = $derived(portrait && exploreLayout.open("panel"));

  // The status bar: the stack's counts while it is shown, where the frame on screen
  // points when it was solved, and the meridian at the site.
  const stackStatus = $derived(stacked?.preview ? { frames: stacked.frames, exposure: stacked.exposure } : null);
  const lastSolution = $derived(live.app.solver?.last ?? null);
  const solved = $derived(!stackStatus && main && solvedShown(preview, lastSolution) ? lastSolution : null);
  const longitude = $derived.by(() => {
    const sites = live.app.sites;
    const site = sites?.active ? sites.saved[sites.active] : null;
    return site?.longitude ?? mount?.site?.longitude ?? null;
  });

  const region = $derived(camera?.region ?? null);
  const subframe = $derived(
    camera !== null &&
      region !== null &&
      (region.width < camera.sensor.width || region.height < camera.sensor.height),
  );
  const coolerOn = $derived(camera ? (camera.cooler ?? camera.target !== null) : false);

  // Frames in a series, kept per device; the stepper's text may be invalid meanwhile.
  let count = $state<number | null>(capture.count);
  $effect(() => {
    if (count !== null) capture.setCount(count);
  });
  const shutterLabel = $derived(main && (count ?? 1) > 1 ? t.live.captureSeries(count ?? 1) : t.live.capture);

  // -- What is on screen --------------------------------------------------------------

  // Save keeps what is on screen (ADR 0054): the live stack while it is shown, else the
  // frame behind the preview. What was saved is said until the image changes.
  let saved = $state<{ url: string; path: string } | null>(null);
  const savedPath = $derived(saved && saved.url === shown?.url ? saved.path : null);
  const saveReason = $derived.by((): string | null => {
    if (!owner) return t.live.saveOwner;
    if (stacked?.preview) return stack?.saving ? t.live.saving : null;
    if (!camera?.solvable) return t.live.saveNothing;
    if (camera.saved) return t.live.savedAlready;
    return null;
  });

  function saveOnScreen(): void {
    const url = shown?.url;
    if (!url) return;
    void act(async () => {
      const result = stacked?.preview ? await saveStack() : await saveShown();
      saved = { url, path: result.path };
    });
  }

  // Solve tells where the frame on screen points, nothing more: syncing belongs to Go
  // and centre. Without a database for the field, a reason instead.
  const solver = $derived(live.app.solver ?? null);
  const solving = $derived(solveJob?.info.state === "running");
  const solveReason = $derived.by((): string | null => {
    if (!solver?.available) return t.solve.unavailable;
    const height = camera?.field?.height;
    if (height !== undefined && solver.databases.length > 0) {
      const covered = solver.databases.some((d) => d.min_fov <= height && height <= d.max_fov);
      if (!covered) return t.solve.noDatabase(`${formatDecimal(height, locale, 2)}°`);
    }
    if (!camera?.solvable) return t.solve.hint(formatPlain(solveExposure(live.app.equipment), locale));
    return null;
  });

  // The JPEG on screen, named after the camera and when it arrived.
  const download = $derived.by(() => {
    if (!shown?.url || !camera) return null;
    const when = (stacked?.preview ? new Date() : new Date(preview?.time ?? Date.now())).toISOString();
    const stamp = when.slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
    const kind = stacked?.preview ? "stack" : camera.device.replace(/[^A-Za-z0-9]+/g, "_");
    return { url: shown.url, name: `NOCS_${kind}_${stamp}.jpg` };
  });
</script>

<svelte:window
  onkeydown={(event) => {
    // A sheet open over the screen takes its Escape first.
    if (event.key === "Escape" && expanded && !document.querySelector("dialog[open]")) expanded = false;
  }} />

<h1 class="visually-hidden">{t.live.title}</h1>

{#if !camera}
  <div class="padded">
    <EmptyState icon="explore" title={t.live.noCamera} body={t.live.noCameraBody}>
      {#snippet action()}
        <Button variant="primary" onclick={() => router.go({ screen: "rig" })}>{t.empty.openRig}</Button>
      {/snippet}
    </EmptyState>
  </div>
{:else}
  <div class="explore" class:portrait class:landscape={!portrait} class:expanded>
    <section class="stage" aria-label={t.live.preview}>
      <div class="image">
        <Viewer
          url={shown?.url ?? null}
          width={shown?.width ?? 0}
          height={shown?.height ?? 0}
          label={stacked?.preview ? t.stack.previewLabel(camera.device) : t.live.previewLabel(camera.device)}
          reticle={framing}
          ontap={() => exploreLayout.toggleOverlays()}>
          {#snippet empty()}
            <div class="nopreview">
              <p class="heading">{t.live.noPreview}</p>
              <p class="muted">{t.live.noPreviewBody}</p>
            </div>
          {/snippet}
          <div class="overlay top" class:goto={exploreLayout.open("goto")}>
            <div class="tools">
              {#if overlays && (cameras.guide_camera || guiding?.phd2.connected)}
                <GuidingTool
                  {guiding}
                  jobs={live.app.jobs}
                  {owner}
                  rig={!!cameras.guide_camera && !!mount}
                  open={exploreLayout.open("guiding")}
                  ontoggle={() => exploreLayout.toggle("guiding")}
                  run={act} />
              {/if}
              {#if overlays && focuser}
                <FocusTool
                  {focuser}
                  autofocus={live.app.autofocus ?? null}
                  {owner}
                  locked={focuserLocked}
                  cameraBusy={!!jobs.running}
                  open={exploreLayout.open("focus")}
                  ontoggle={() => exploreLayout.toggle("focus")}
                  onsheet={() => (device = "focuser")}
                  run={act} />
              {/if}
            </div>
            <div class="buttons">
              <div class="row">
                {#if overlays}<span class="theme"><ThemeButton /></span>{/if}
                <button
                  type="button"
                  class="icon-button"
                  aria-label={overlays ? t.live.overlaysHide : t.live.overlaysShow}
                  aria-pressed={!overlays}
                  onclick={() => exploreLayout.toggleOverlays()}>
                  <Icon name={overlays ? "eye" : "eyeOff"} />
                </button>
                <button
                  type="button"
                  class="icon-button"
                  aria-label={expanded ? t.live.shrink : t.live.expand}
                  aria-pressed={expanded}
                  onclick={() => (expanded = !expanded)}>
                  <Icon name={expanded ? "shrink" : "expand"} />
                </button>
              </div>
              {#if overlays && available.length > 1}
                <PillSwitch
                  label={t.live.camera}
                  options={available.map((value) => ({ value, label: t.roles[value] }))}
                  value={role}
                  onchange={(value) => capture.setRole(value)} />
              {/if}
              {#if overlays && mount}
                <GoToTool {mount} {owner} open={exploreLayout.open("goto")} ontoggle={() => exploreLayout.toggle("goto")} />
              {/if}
            </div>
          </div>
        </Viewer>
      </div>
      {#if overlays}
        <HistogramBar
          preview={stacked?.preview ? null : preview}
          none={stacked?.preview ? t.live.histogramNone : t.live.noPreview}
          open={exploreLayout.open("histogram")}
          scale={exploreLayout.scale}
          ontoggle={() => exploreLayout.toggle("histogram")}
          onscale={(scale) => exploreLayout.setScale(scale)} />
      {/if}
      <FrameStatus
        {camera}
        preview={stacked?.preview ? null : preview}
        stack={stackStatus}
        {status}
        {solved}
        {mount}
        {longitude} />
    </section>

    <section class="panel" class:open={sheetOpen} aria-label={t.live.controls}>
      <div class="body">
        {#if main && stack}
          <StackCard {stack} {owner} run={act} />
        {/if}

        {#if wheel}
          <div class="filters">
            {#if !wheel.confirmed && wheel.key && owner}
              <Banner icon="filter" tone="warning">
                {t.rig.wheelNew}
                {#snippet action()}
                  <Button variant="text" onclick={() => (device = "filter_wheel")}>{t.live.setFilters}</Button>
                {/snippet}
              </Banner>
            {/if}
            <SegmentedControl
              label={t.live.filter}
              options={Array.from({ length: wheel.slots }, (_, i) => ({
                value: String(i + 1),
                label: slotLabel(wheel, i + 1, t),
              }))}
              value={String(wheel.slot ?? "")}
              disabled={!owner || wheelLocked || wheel.moving}
              onchange={pickFilter} />
            {#if wheel.moving || wheelJob?.info.kind === "filter"}
              <p class="caption muted" role="status">{t.live.filterMoving}</p>
            {/if}
          </div>
        {/if}

        {#if inUse}<Banner icon="guide">{t.live.guideInUse}</Banner>{/if}

        {#if main}
          <Stepper
            label={t.live.frames}
            bind:value={count}
            min={1}
            max={MAX_SERIES}
            hint={t.live.framesHint}
            disabled={!owner || !!running} />
        {/if}

        <div class="tiles">
          <Tile
            label={t.live.exposure}
            value={formatSeconds(camera.exposure, locale)}
            disabled={!owner || !!running || inUse}
            onclick={() => (editing = "exposure")} />
          <Tile
            label={t.live.gain}
            value={camera.gain === null ? "—" : formatPlain(camera.gain, locale)}
            disabled={!owner || !!running || inUse || !camera.gain_range}
            onclick={() => (editing = "gain")} />
          <Tile
            label={t.live.offset}
            value={camera.offset === null ? "—" : formatPlain(camera.offset, locale)}
            disabled={!owner || !!running || inUse || !camera.offset_range}
            onclick={() => (editing = "offset")} />
          <Tile
            label={t.live.binning}
            value="{camera.binning[0]}×{camera.binning[1]}"
            disabled={!owner || !!running || inUse || camera.max_binning <= 1}
            onclick={() => (editing = "binning")} />
          <Tile
            label={t.live.cooler}
            value={!camera.can_cool
              ? t.live.coolerNone
              : !coolerOn
                ? t.live.coolerOff
                : camera.target !== null
                  ? formatTemperature(camera.target, locale, 0)
                  : t.live.coolerOn}
            word={!camera.can_cool || !coolerOn || camera.target === null}
            detail={camera.temperature === null ? undefined : formatTemperature(camera.temperature, locale)}
            disabled={!owner || !camera.can_cool}
            onclick={() => (editing = "cooling")} />
        </div>

        {#if subframe && region}
          <div class="region">
            <span class="mono">{t.live.region(region.width, region.height)}</span>
            <Button
              variant="text"
              disabled={!owner || !!running}
              onclick={() => void act(() => setCameraSettings(role, { region: "full" }))}>
              {t.live.fullFrame}
            </Button>
          </div>
        {/if}
        {#if running && owner}<p class="caption muted">{t.live.locked}</p>{/if}
      </div>

      <!-- The actions stay in reach while the panel scrolls, or while its sheet is
           folded on an upright screen: the primary action and what went wrong. -->
      <div class="dock">
        {#if portrait}
          <button
            type="button"
            class="handle"
            aria-expanded={sheetOpen}
            onclick={() => exploreLayout.toggle("panel")}>
            <Icon name={sheetOpen ? "chevronDown" : "up"} size={18} />
            {sheetOpen ? t.live.panelClose : t.live.panelOpen}
          </button>
        {/if}
        <SequenceHold resources={[role, "filter_wheel", "focuser"]} />
        {#if actionError}
          <Banner icon="alert" tone="error">
            {actionError}
            {#snippet action()}
              <Button variant="text" onclick={() => (actionError = "")}>{t.live.dismiss}</Button>
            {/snippet}
          </Banner>
        {/if}
        {#if failed}
          <Banner icon="alert" tone="error">
            {failure}
            {#snippet action()}
              <Button variant="text" onclick={() => (dismissed = failed.id)}>{t.live.dismiss}</Button>
            {/snippet}
          </Banner>
        {/if}
        <div class="actions">
          <button
            type="button"
            class="action"
            class:on={looping}
            aria-pressed={looping}
            disabled={!owner || busy || inUse || (!!running && !looping)}
            onclick={toggleLoop}>
            <Icon name="loop" />
            {t.live.loop}
          </button>
          <Shutter
            running={!!running}
            {progress}
            label={running ? t.live.stop : shutterLabel}
            disabled={!owner || busy || inUse}
            onclick={shoot} />
          {#if main}
            <button
              type="button"
              class="action"
              disabled={busy || saveReason !== null || savedPath !== null}
              onclick={saveOnScreen}>
              <Icon name="save" />
              {t.live.save}
            </button>
          {:else}
            <span class="action placeholder" aria-hidden="true"></span>
          {/if}
        </div>
        <div class="more">
          {#if main && solver}
            <button
              type="button"
              class="small"
              disabled={!owner || busy || solving || solveReason !== null}
              onclick={() => void act(() => solve({ frame: "last" }))}>
              <Icon name="plan" size={18} />
              {solving ? t.live.status.solving : t.solve.solve}
            </button>
          {/if}
          {#if download}
            <a class="small" href={download.url} download={download.name}>
              <Icon name="download" size={18} />
              {t.live.download}
            </a>
          {/if}
        </div>
        <p class="caption muted outcome" aria-live="polite">
          {#if savedPath}
            {t.live.saved(savedPath)}
          {:else if main}
            {saveReason ?? (owner && solver && solveReason ? solveReason : t.live.saveHint)}
          {/if}
        </p>
      </div>
    </section>
  </div>

  {#if editing}
    <SettingSheet setting={editing} {role} {camera} onclose={() => (editing = null)} />
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
  /* The screen's height without the tab bar (phones) or the rail (from 768 px). */
  .explore {
    --available: calc(100dvh - var(--tabbar-height) - env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    height: var(--available);
  }
  @media (min-width: 768px) {
    .explore {
      --available: 100dvh;
    }
  }
  .landscape {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(300px, 32vw, 400px);
  }
  .stage {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    flex: 1 1 auto;
  }
  .image {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
  }
  .expanded .stage {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: #000;
  }
  .overlay {
    position: absolute;
    left: 0;
    right: 0;
    display: flex;
    gap: var(--space-2);
    padding: var(--space-3);
    pointer-events: none;
  }
  .overlay :global(button),
  .overlay :global(a),
  .overlay :global([data-overlay]),
  .overlay :global(dialog) {
    pointer-events: auto;
  }
  /* Over the whole image, in two columns that scroll when their tools are taller
     than it: each tool takes at most its column's width. (No container query: it
     would make the image the containing block of the sheets the tools open.) */
  .top {
    top: env(safe-area-inset-top);
    bottom: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
  }
  /* Upright, one column: the buttons (and go to) first, then the tools on the left;
     one tool is open at a time, as wide as the image. */
  .portrait .top {
    display: flex;
    flex-direction: column;
  }
  /* The side holding the open tool gives way when the image is short. */
  .portrait .buttons {
    order: -1;
    flex: 0 0 auto;
  }
  .portrait .tools {
    flex: 0 1 auto;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .portrait .goto .buttons {
    flex-shrink: 1;
  }
  .portrait .goto .tools {
    flex-shrink: 0;
  }
  .portrait .buttons :global(.card),
  .portrait .tools :global(.card) {
    width: 100%;
  }
  .tools,
  .buttons {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .buttons {
    align-items: flex-end;
  }
  .tools {
    align-items: flex-start;
  }
  .row {
    display: flex;
    gap: var(--space-2);
  }
  .icon-button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    color: var(--text);
    cursor: pointer;
  }
  .nopreview {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  /* The panel: a column at the image's side, scrolling, with its actions at the foot. */
  .panel {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--bg);
  }
  .landscape .panel {
    border-left: 1px solid var(--line);
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-4) var(--space-3);
  }
  .landscape .body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
  }
  /* Upright: the actions under the image, the rest in a sheet that opens over it. */
  .portrait .panel {
    position: relative;
    flex: none;
  }
  .portrait .body {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 100%;
    z-index: 4;
    max-height: calc(var(--available) * 0.62);
    overflow-y: auto;
    border-top: 1px solid var(--line);
    border-radius: var(--radius-card) var(--radius-card) 0 0;
    background: var(--bg);
    box-shadow: 0 -8px 24px rgb(0 0 0 / 40%);
  }
  .portrait .panel:not(.open) .body {
    display: none;
  }
  .handle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    min-height: 32px;
    border: 0;
    background: transparent;
    color: var(--muted);
    font-size: 14px;
    cursor: pointer;
  }

  .filters {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .region {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    margin-top: calc(-1 * var(--space-2));
  }
  .dock {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4) var(--space-3);
    border-top: 1px solid var(--line);
    background: var(--bg);
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
    border-radius: var(--radius-button);
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
  /* Pressed: a filled tile in the accent's tint, not only a color change. */
  .action.on {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) var(--tint), var(--surface));
    color: var(--accent);
  }
  .placeholder {
    visibility: hidden;
  }
  .more {
    display: flex;
    justify-content: center;
    gap: var(--space-2);
  }
  .small {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--accent);
    font-size: 15px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
  }
  .small:disabled {
    color: var(--muted);
    cursor: default;
    opacity: 0.6;
  }
  .outcome {
    min-height: 16px;
    text-align: center;
    overflow-wrap: anywhere;
  }

  /* The navigation rail carries the theme button on wide screens. */
  @media (min-width: 768px) {
    .theme {
      display: none;
    }
  }
</style>
