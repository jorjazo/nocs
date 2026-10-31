<script lang="ts">
  // Live view: the latest preview of a camera with its metrics and histogram,
  // exposure settings, filter, cooling, and loop / capture with or without
  // saving (docs/ux.md §2). Settings, the exposure time included, are kept by
  // the server and shared by every client; the save choice belongs to this device.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import ThemeButton from "../../components/ThemeButton.svelte";
  import Tile from "../../components/Tile.svelte";
  import { cancelJob, expose, loop, setCameraSettings } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import {
    CAMERA_ROLES,
    cameraJobs,
    capture,
    filterWheel,
    MAX_LOOP_EXPOSURE,
    selectFilter,
  } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import Histogram from "./Histogram.svelte";
  import SettingSheet, { type Setting } from "./SettingSheet.svelte";
  import Shutter from "./Shutter.svelte";
  import Viewer from "./Viewer.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const cameras = $derived(live.app.cameras ?? {});
  const available = $derived(CAMERA_ROLES.filter((role) => cameras[role]));
  const role = $derived(available.includes(capture.role) ? capture.role : (available[0] ?? "main_camera"));
  const camera = $derived(cameras[role] ?? null);
  const preview = $derived(camera?.preview ?? null);
  const owner = $derived(auth.owner);

  // Only the main camera saves frames, and only it gets the filter (ADR 0013).
  const main = $derived(role === "main_camera");
  const wheel = $derived(main ? filterWheel(live.app) : null);
  const filterName = $derived.by(() => {
    if (!wheel?.slot) return null;
    return wheel.names[wheel.slot - 1] || t.live.slot(wheel.slot);
  });

  // -- Jobs -------------------------------------------------------------------------

  const jobs = $derived(cameraJobs(live.app.jobs, role));
  const running = $derived(jobs.running);
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
  const failed = $derived(
    jobs.latest?.info.state === "failed" && jobs.latest.id !== dismissed ? jobs.latest : null,
  );
  const savedPath = $derived.by(() => {
    const latest = jobs.latest?.info;
    if (latest?.kind !== "expose" || latest.state !== "succeeded") return null;
    const path = latest.result?.path;
    return typeof path === "string" ? path : null;
  });

  const status = $derived.by((): { tone: Tone; text: string } | null => {
    if (running) {
      if (remaining !== null) {
        const left = formatPlain(Math.ceil(remaining), locale);
        if (looping) return { tone: "accent", text: t.live.status.loopLeft(left) };
        if (total) {
          const elapsed = formatPlain(Math.max(0, Math.floor(total - remaining)), locale);
          return { tone: "accent", text: t.live.status.exposing(elapsed, formatPlain(total, locale)) };
        }
        return { tone: "accent", text: t.live.status.left(left) };
      }
      return { tone: "accent", text: looping ? t.live.status.looping : t.live.status.processing };
    }
    if (failed) return { tone: "error", text: t.live.status.failed };
    return null;
  });

  // -- Actions -------------------------------------------------------------------------

  let busy = $state(false);
  let actionError = $state("");

  async function act(action: () => Promise<void>): Promise<void> {
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
      await expose(role, exposure, main ? capture.save : undefined);
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
      await loop(role, exposure);
    });
  }

  function pickFilter(value: string): void {
    if (wheel) void act(() => selectFilter(wheel, Number(value)));
  }

  // -- Layout ----------------------------------------------------------------------------

  let editing = $state<Setting | null>(null);
  let expanded = $state(false);

  const region = $derived(camera?.region ?? null);
  const subframe = $derived(
    camera !== null &&
      region !== null &&
      (region.width < camera.sensor.width || region.height < camera.sensor.height),
  );
  const coolerOn = $derived(camera ? (camera.cooler ?? camera.target !== null) : false);
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && expanded && !editing) expanded = false;
  }} />

<h1 class="visually-hidden">{t.live.title}</h1>

{#if !camera}
  <div class="padded">
    <EmptyState icon="live" title={t.live.noCamera} body={t.live.noCameraBody}>
      {#snippet action()}
        <Button variant="primary" onclick={() => router.go({ screen: "rig" })}>{t.empty.openRig}</Button>
      {/snippet}
    </EmptyState>
  </div>
{:else}
  <div class="live" class:expanded>
    <section class="stage" aria-label={t.live.preview}>
      <Viewer
        url={preview?.url ?? null}
        width={preview?.width ?? 0}
        height={preview?.height ?? 0}
        label={t.live.previewLabel(camera.device)}>
        {#snippet empty()}
          <div class="nopreview">
            <p class="heading">{t.live.noPreview}</p>
            <p class="muted">{t.live.noPreviewBody}</p>
          </div>
        {/snippet}
        <div class="overlay top">
          <!-- The camera as it is now; the bottom row describes the preview. -->
          <span class="device">
            <span class="name">{camera.device}</span>
            {#if camera.temperature !== null || filterName}
              <span class="mono">
                {[camera.temperature === null ? null : formatTemperature(camera.temperature, locale), filterName]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            {/if}
          </span>
          <span class="buttons">
            <span class="theme"><ThemeButton /></span>
            <button
              type="button"
              class="icon-button"
              aria-label={expanded ? t.live.shrink : t.live.expand}
              aria-pressed={expanded}
              onclick={() => (expanded = !expanded)}>
              <Icon name={expanded ? "shrink" : "expand"} />
            </button>
          </span>
        </div>
        <div class="overlay bottom">
          {#if preview}
            <span class="pill mono">{preview.hfr === null ? "HFR —" : `HFR ${formatDecimal(preview.hfr, locale, 2)}`}</span>
            <span class="pill mono">{t.live.stars(preview.stars)}</span>
            <span class="pill mono">{formatSeconds(preview.exposure, locale)}</span>
          {/if}
          {#if status}
            <span class="status" role="status"><Chip tone={status.tone}>{status.text}</Chip></span>
          {/if}
        </div>
      </Viewer>
    </section>

    <section class="panel" aria-label={t.live.controls}>
      {#if available.length > 1}
        <SegmentedControl
          label={t.live.camera}
          options={available.map((value) => ({ value, label: t.roles[value] }))}
          value={role}
          onchange={(value) => (capture.role = value)} />
      {/if}

      {#if preview}
        <Histogram {preview} label={t.live.histogram} note={t.live.autoStretch} />
      {/if}

      {#if wheel}
        <div class="filters">
          <SegmentedControl
            label={t.live.filter}
            options={wheel.names.map((name, i) => ({ value: String(i + 1), label: name || t.live.slot(i + 1) }))}
            value={String(wheel.slot ?? "")}
            onchange={pickFilter} />
          {#if wheel.moving}<p class="caption muted" role="status">{t.live.filterMoving}</p>{/if}
        </div>
      {/if}

      <div class="tiles">
        <Tile
          label={t.live.exposure}
          value={formatSeconds(camera.exposure, locale)}
          disabled={!owner || !!running}
          onclick={() => (editing = "exposure")} />
        <Tile
          label={t.live.gain}
          value={camera.gain === null ? "—" : formatPlain(camera.gain, locale)}
          disabled={!owner || !!running || !camera.gain_range}
          onclick={() => (editing = "gain")} />
        <Tile
          label={t.live.offset}
          value={camera.offset === null ? "—" : formatPlain(camera.offset, locale)}
          disabled={!owner || !!running || !camera.offset_range}
          onclick={() => (editing = "offset")} />
        <Tile
          label={t.live.binning}
          value="{camera.binning[0]}×{camera.binning[1]}"
          disabled={!owner || !!running || camera.max_binning <= 1}
          onclick={() => (editing = "binning")} />
        <Tile
          label={t.live.frame}
          value={t.live.frameTypes[camera.frame_type]}
          word
          disabled={!owner || !!running}
          onclick={() => (editing = "frame")} />
        <Tile
          label={t.live.cooler}
          value={camera.temperature === null
            ? t.live.coolerNone
            : !coolerOn
              ? t.live.coolerOff
              : camera.target !== null
                ? formatTemperature(camera.target, locale, 0)
                : t.live.coolerOn}
          word={!coolerOn || camera.target === null}
          detail={camera.temperature === null ? undefined : formatTemperature(camera.temperature, locale)}
          disabled={!owner || camera.temperature === null}
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

      <!-- On phones the actions stay above the tab bar while the panel scrolls:
           the primary action and what went wrong are always in reach. -->
      <div class="dock">
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
            {failed.info.error ?? t.live.status.failed}
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
            disabled={!owner || busy || (!!running && !looping)}
            onclick={toggleLoop}>
            <Icon name="loop" />
            {t.live.loop}
          </button>
          <Shutter
            running={!!running}
            {progress}
            label={running ? t.live.stop : main && capture.save ? t.live.captureSave : t.live.capture}
            disabled={!owner || busy}
            onclick={shoot} />
          {#if main}
            <button
              type="button"
              class="action"
              class:on={capture.save}
              aria-pressed={capture.save}
              disabled={!owner}
              onclick={() => capture.setSave(!capture.save)}>
              <Icon name="save" />
              {t.live.save}
            </button>
          {:else}
            <span class="action placeholder" aria-hidden="true"></span>
          {/if}
        </div>
        <p class="caption muted outcome" aria-live="polite">
          {#if savedPath}{t.live.saved(savedPath)}{:else if main}{capture.save ? t.live.willSave : t.live.wontSave}{/if}
        </p>
      </div>
    </section>
  </div>

  {#if editing}
    <SettingSheet setting={editing} {role} {camera} onclose={() => (editing = null)} />
  {/if}
{/if}

<style>
  .padded {
    padding: 0 var(--margin);
  }
  .stage {
    height: min(48dvh, 80vw);
    min-height: 240px;
  }
  .expanded .stage {
    position: fixed;
    inset: 0;
    z-index: 20;
    height: auto;
  }
  .overlay {
    position: absolute;
    left: 0;
    right: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3);
    pointer-events: none;
  }
  .overlay > :global(*) {
    pointer-events: auto;
  }
  .top {
    top: env(safe-area-inset-top);
    justify-content: space-between;
    align-items: flex-start;
  }
  .bottom {
    bottom: 0;
  }
  .buttons {
    display: flex;
    gap: var(--space-2);
  }
  .pill {
    display: inline-flex;
    align-items: center;
    min-height: 32px;
    padding: 0 12px;
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    font-size: 14px;
    white-space: nowrap;
  }
  .device {
    display: flex;
    flex-direction: column;
    min-width: 0;
    max-width: calc(100% - 112px);
    padding: 6px 12px;
    border-radius: var(--radius-tile);
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    font-size: 14px;
    line-height: 20px;
  }
  .device > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .name {
    font-weight: 600;
  }
  .status {
    margin-left: auto;
  }
  .icon-button {
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
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
  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--margin) 0;
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
    position: sticky;
    bottom: calc(var(--tabbar-height) + env(safe-area-inset-bottom));
    z-index: 2;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0 calc(-1 * var(--margin));
    padding: var(--space-2) var(--margin);
    background: var(--bg);
  }
  .actions {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: var(--space-4);
  }
  .action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--primary-height);
    padding: 0 var(--space-3);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    font-size: 17px;
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
    .dock {
      bottom: 0;
    }
  }

  @media (min-width: 900px) {
    .live {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 400px;
      min-height: 100dvh;
    }
    .stage {
      position: sticky;
      top: 0;
      height: 100dvh;
    }
    .panel {
      padding: var(--space-6) var(--space-6) 0;
      border-left: 1px solid var(--line);
    }
    .dock {
      margin: 0 calc(-1 * var(--space-6));
      padding: var(--space-3) var(--space-6) var(--space-4);
    }
  }
</style>
