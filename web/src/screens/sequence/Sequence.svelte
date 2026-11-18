<script lang="ts">
  // Sequences: run groups of frames of what the camera has framed (lights through
  // each filter, darks, bias, flats) without going anywhere else. Explore's base
  // (the image, its histogram and status bar, guiding and focus over it), with the
  // sequence's widget where Explore has its go to, and a panel with what the sequence
  // does around its groups. Explore and Sequences exclude each other.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import ImageScreen from "../../components/ImageScreen.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { estimateTemplate, pauseSequence, resumeSequence, startSequence, stopSequence } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { solvedShown } from "../../lib/explore";
  import { exploreLayout } from "../../lib/explore.svelte";
  import { formatBytes, formatDuration, formatPlain, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import { currentRow, isActive, workingView } from "../../lib/sequence";
  import {
    coolingSummary,
    endSummary,
    focusSummary,
    groupName,
    pointingSummary,
    sequences,
    windowSummary,
  } from "../../lib/sequence.svelte";
  import { stackView, type StackView } from "../../lib/stackview.svelte";
  import type { SequenceEstimate } from "../../lib/types";
  import FocuserSheet from "../devices/FocuserSheet.svelte";
  import FocusTool from "../explore/FocusTool.svelte";
  import FrameStatus from "../explore/FrameStatus.svelte";
  import GuidingTool from "../explore/GuidingTool.svelte";
  import HistogramBar from "../explore/HistogramBar.svelte";
  import ImageOverlay from "../explore/ImageOverlay.svelte";
  import Viewer from "../explore/Viewer.svelte";
  import { prompting } from "./prompting.svelte";
  import SequenceSheets, { type SheetKind } from "./SequenceSheets.svelte";
  import SequenceTool from "./SequenceTool.svelte";
  import StopSheet from "./StopSheet.svelte";

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);

  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const cameras = $derived(live.app.cameras ?? {});
  const preview = $derived(camera?.preview ?? null);
  const guiding = $derived(live.app.guiding ?? null);
  const mount = $derived(live.app.mount ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const outputs = $derived(live.app.power?.outputs ?? []);
  const run = $derived(live.app.sequence?.run ?? null);
  // The run while it is active (holds the rig, or waits paused or on the user).
  const going = $derived(isActive(run) ? run : null);
  const active = $derived(going !== null);
  const events = $derived(live.app.sequence?.events ?? []);
  const working = $derived(workingView(run, live.app.jobs));

  // The sequence shown: the running one, or the one chosen last on this device.
  $effect(() => {
    const running = going?.sequence ?? null;
    if (!owner) return;
    if (!sequences.loaded || (running && running !== sequences.id)) void sequences.load(running);
  });
  const draft = $derived(sequences.draft);
  // The run shown is this sequence's (the last one, once it ended).
  const ownRun = $derived(run && (active || run.sequence === sequences.id) ? run : null);
  const editable = $derived(owner && !active && draft !== null);
  $effect(() => {
    if (!draft) return;
    void JSON.stringify(draft);
    sequences.changed();
  });

  // -- The image -----------------------------------------------------------------

  // The group's stack: the live stack while lights are taken, the latest master of a
  // group of darks, bias or flats otherwise.
  const plan = $derived(going?.current ? (going.plans[going.current] ?? null) : null);
  const master = $derived(live.app.sequence?.master ?? null);
  const stack = $derived(live.app.stack?.current ?? null);
  const groupStack = $derived.by(() => {
    if (plan && plan.frame_type !== "light") return master?.preview ?? null;
    return stack?.preview ?? master?.preview ?? null;
  });
  const showStack = $derived(stackView.view === "stack" && groupStack !== null);
  const shown = $derived(showStack ? groupStack : preview);
  const stackStatus = $derived(showStack && stack?.preview === groupStack && stack ? { frames: stack.frames, exposure: stack.exposure } : null);
  const lastSolution = $derived(live.app.solver?.last ?? null);
  const solved = $derived(!showStack && solvedShown(preview, lastSolution) ? lastSolution : null);
  const longitude = $derived.by(() => {
    const sites = live.app.sites;
    const site = sites?.active ? sites.saved[sites.active] : null;
    return site?.longitude ?? mount?.site?.longitude ?? null;
  });

  // The frame in progress, for the widget and the status bar.
  const exposingRow = $derived(
    going && going.step?.kind === "expose" && camera?.exposing ? currentRow(going, live.app.filter_wheel?.filter ?? null) : null,
  );
  const exposing = $derived(
    exposingRow
      ? {
          label: groupName({ frame_type: exposingRow.frameType, filter: exposingRow.filter, count: exposingRow.count }, t),
          frame: Math.min(exposingRow.done + 1, exposingRow.count),
          count: exposingRow.count,
          remaining: camera?.remaining ?? null,
          total: exposingRow.exposure ?? camera?.exposure ?? 0,
        }
      : null,
  );
  const status = $derived.by((): { tone: Tone; text: string } | null => {
    if (!going) return null;
    if (going.prompt) return { tone: "warning", text: s.state.waiting };
    if (exposing && exposing.remaining !== null) {
      const total = formatPlain(exposing.total, locale);
      const elapsed = formatPlain(Math.max(0, Math.floor(exposing.total - exposing.remaining)), locale);
      return { tone: "accent", text: `${exposing.frame}/${exposing.count} · ${t.live.status.exposing(elapsed, total)}` };
    }
    return { tone: going.state === "paused" ? "warning" : "accent", text: t.session.states[going.state === "finished" ? "completed" : going.state] };
  });

  const focuserJob = $derived(holder(live.app.jobs, "focuser"));
  const focuserLocked = $derived(focuserJob !== null && focuserJob.info.kind !== "focus");

  // -- What it costs ----------------------------------------------------------------

  let estimate = $state<SequenceEstimate | null>(null);
  let problem = $state("");
  let asked = 0;
  $effect(() => {
    if (!draft) return;
    const body = $state.snapshot(draft);
    const id = ++asked;
    const timer = setTimeout(() => {
      estimateTemplate(body)
        .then((found) => {
          if (id !== asked) return;
          estimate = found;
          problem = "";
        })
        .catch((e) => {
          if (id === asked) problem = errorText(e, t);
        });
    }, 300);
    return () => clearTimeout(timer);
  });
  const destination = $derived.by(() => {
    const storage = live.app.storage;
    return storage?.destinations.find((d) => d.id === storage.destination) ?? null;
  });

  // -- Actions -----------------------------------------------------------------------

  let busy = $state<"start" | "pause" | "resume" | "stop" | null>(null);
  let error = $state("");
  let stopping = $state(false);
  let sheet = $state<SheetKind | null>(null);
  let focuserSheet = $state(false);
  let expanded = $state(false);
  let creating = $state(false);

  async function act(what: NonNullable<typeof busy>, call: () => Promise<unknown>): Promise<void> {
    busy = what;
    error = "";
    try {
      await call();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  async function tool(call: () => Promise<unknown>): Promise<void> {
    error = "";
    try {
      await call();
    } catch (e) {
      error = errorText(e, t);
    }
  }

  function start(): void {
    const id = sequences.id;
    if (!id) return;
    void act("start", async () => {
      await sequences.save();
      await startSequence(id);
    });
  }

  function stop(now: boolean, runEnd: boolean): void {
    stopping = false;
    void act("stop", () => stopSequence({ now, run_end: runEnd }));
  }

  async function create(): Promise<void> {
    creating = true;
    error = "";
    try {
      const wheel = live.app.filter_wheel ?? null;
      const filters = (wheel?.names ?? []).filter((name) => name);
      await sequences.create(
        s.newName,
        wheel?.filter ?? filters[0] ?? null,
        !!live.app.equipment?.devices.guide_camera,
        live.app.solver?.available === true,
        { gain: camera?.gain ?? null, offset: camera?.offset ?? null },
      );
      router.go({ screen: "sequence-edit" });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      creating = false;
    }
  }

  const portrait = $derived(exploreLayout.orientation === "portrait");
  const overlays = $derived(exploreLayout.overlays);
  const sheetOpen = $derived(portrait && exploreLayout.open("panel"));
  const lights = $derived((draft?.groups ?? []).filter((g) => (g.frame_type ?? "light") === "light").length);
  const canGuide = $derived(!!live.app.equipment?.devices.guide_camera);
  const promptKey = $derived(going?.prompt ? `${going.run}:${going.current}:${going.prompt}` : null);
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && expanded && !document.querySelector("dialog[open]")) expanded = false;
  }} />

<h1 class="visually-hidden">{s.title}</h1>

{#if !owner}
  <div class="padded"><EmptyState icon="sequence" title={s.ownerOnly} body="" /></div>
{:else if !camera}
  <div class="padded">
    <EmptyState icon="sequence" title={t.live.noCamera} body={t.live.noCameraBody}>
      {#snippet action()}
        <Button variant="primary" onclick={() => router.go({ screen: "rig" })}>{t.empty.openRig}</Button>
      {/snippet}
    </EmptyState>
  </div>
{:else}
  <ImageScreen
    {portrait}
    {expanded}
    {sheetOpen}
    stageLabel={t.live.preview}
    panelLabel={t.live.controls}
    openLabel={t.live.panelOpen}
    closeLabel={t.live.panelClose}
    ontogglesheet={() => exploreLayout.toggle("panel")}>
    {#snippet image()}
      <Viewer
        url={shown?.url ?? null}
        width={shown?.width ?? 0}
        height={shown?.height ?? 0}
        label={showStack ? t.stack.previewLabel(camera.device) : t.live.previewLabel(camera.device)}
        reticle={false}
        ontap={() => exploreLayout.toggleOverlays()}>
        {#snippet empty()}
          <div class="nopreview">
            <p class="heading">{t.live.noPreview}</p>
          </div>
        {/snippet}
        <ImageOverlay
          {portrait}
          {overlays}
          {expanded}
          wide={exploreLayout.open("sequence")}
          ontoggleoverlays={() => exploreLayout.toggleOverlays()}
          ontoggleexpanded={() => (expanded = !expanded)}>
          {#snippet tools()}
            {#if cameras.guide_camera || guiding?.phd2.connected}
              <GuidingTool
                {guiding}
                jobs={live.app.jobs}
                {owner}
                rig={!!cameras.guide_camera && !!mount}
                open={exploreLayout.open("guiding")}
                ontoggle={() => exploreLayout.toggle("guiding")}
                run={tool} />
            {/if}
            {#if focuser}
              <FocusTool
                {focuser}
                autofocus={live.app.autofocus ?? null}
                {owner}
                locked={focuserLocked}
                cameraBusy={!!going && going.state !== "paused"}
                open={exploreLayout.open("focus")}
                ontoggle={() => exploreLayout.toggle("focus")}
                onsheet={() => (focuserSheet = true)}
                run={tool} />
            {/if}
          {/snippet}
          {#snippet side()}
            <SequenceTool
              run={ownRun}
              template={draft}
              events={ownRun ? events : []}
              {exposing}
              {outputs}
              open={exploreLayout.open("sequence")}
              ontoggle={() => exploreLayout.toggle("sequence")} />
          {/snippet}
        </ImageOverlay>
      </Viewer>
    {/snippet}
    {#snippet under()}
      {#if overlays}
        <HistogramBar
          preview={showStack ? null : preview}
          none={showStack ? t.live.histogramNone : t.live.noPreview}
          open={exploreLayout.open("histogram")}
          scale={exploreLayout.scale}
          ontoggle={() => exploreLayout.toggle("histogram")}
          onscale={(scale) => exploreLayout.setScale(scale)} />
      {/if}
      <FrameStatus {camera} preview={showStack ? null : preview} stack={stackStatus} {status} {solved} {mount} {longitude} />
    {/snippet}
    {#snippet body()}
      <SegmentedControl
        label={s.show}
        options={[
          { value: "frame" as StackView, label: s.showFrame },
          { value: "stack" as StackView, label: s.showStack },
        ]}
        value={stackView.view}
        onchange={(view) => stackView.set(view)} />
      {#if stackView.view === "stack" && !groupStack}
        <p class="caption muted">{plan && plan.frame_type !== "light" ? s.masterLater : s.stackLater}</p>
      {/if}

      {#if !draft}
        {#if sequences.loaded}
          <EmptyState icon="sequence" title={s.none} body={s.noneBody}>
            {#snippet action()}
              <Button variant="primary" busy={creating} onclick={() => void create()}>{s.create}</Button>
            {/snippet}
          </EmptyState>
        {:else}
          <p class="muted" role="status">{s.loading}</p>
        {/if}
      {:else}
        <div class="title">
          <h2>{draft.name}</h2>
          <a class="link" href="#/sequence/edit">{s.configure}</a>
        </div>
        {#if active}<p class="caption muted">{s.readOnly}</p>{/if}
        <ul class="options">
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "focus")}>
              <span class="text"><span class="name">{s.autofocus}</span><span class="muted small">{focusSummary(draft, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "pointing")}>
              <span class="text"><span class="name">{s.pointing}</span><span class="muted small">{pointingSummary(draft, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          <li>
            <Toggle
              label={s.guiding}
              hint={canGuide || draft.guide ? s.guidingHint : s.noGuiding}
              checked={draft.guide ?? false}
              disabled={!editable || (!canGuide && !draft.guide)}
              onchange={(on) => (draft.guide = on)} />
          </li>
          <li>
            <Toggle
              label={s.flip}
              hint={draft.flip !== false ? s.flipHint(formatPlain(draft.flip_after ?? 5, locale)) : s.flipOff}
              checked={draft.flip !== false}
              disabled={!editable}
              onchange={(on) => (draft.flip = on)} />
          </li>
          {#if draft.guide}
            <li>
              <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "dither")}>
                <span class="text">
                  <span class="name">{s.dither}</span>
                  <span class="muted small">
                    {draft.dither_every != null ? s.ditherOn(draft.dither_every, formatPlain(draft.dither_pixels ?? 5, locale)) : s.off}
                  </span>
                </span>
                <Icon name="chevronRight" />
              </button>
            </li>
          {/if}
          {#if lights > 1}
            <li>
              <Toggle
                label={s.rotate}
                hint={draft.order === "in_turn" ? s.rotateOff : s.rotateOn(draft.batch ?? 5)}
                checked={draft.order !== "in_turn"}
                disabled={!editable}
                onchange={(on) => (draft.order = on ? "batches" : "in_turn")} />
            </li>
          {/if}
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "night")}>
              <span class="text"><span class="name">{s.night}</span><span class="muted small">{windowSummary(draft, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          {#if camera.can_cool || (draft.cooling ?? "off") !== "off"}
            <li>
              <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "cooling")}>
                <span class="text"><span class="name">{s.cooling}</span><span class="muted small">{coolingSummary(draft, t, locale)}</span></span>
                <Icon name="chevronRight" />
              </button>
            </li>
          {/if}
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "end")}>
              <span class="text"><span class="name">{s.whenFinished}</span><span class="muted small">{endSummary(draft, t, outputs)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
        </ul>
        {#if estimate && !active}
          <p class="muted small">
            {s.imagingTime}: {formatDuration(estimate.duration)}{estimate.ends ? ` · ${s.endsAt(formatTime(estimate.ends, locale))}` : ""}
            · {destination ? s.framesOn(estimate.frames, destination.label) : s.framesTotal(estimate.frames)}
            {#if estimate.bytes !== null}· {formatBytes(estimate.bytes, locale)}{/if}
          </p>
        {/if}
        {#if problem && !active}<Banner icon="alert" tone="error">{problem}</Banner>{/if}
      {/if}
    {/snippet}
    {#snippet dock()}
      {#if working === "explore"}
        <Banner icon="explore" tone="warning">
          {s.exploreWorking}
          {#snippet action()}
            <Button variant="text" onclick={() => router.go({ screen: "explore" })}>{s.openExplore}</Button>
          {/snippet}
        </Banner>
      {/if}
      {#if going?.prompt}
        <Banner icon="alert" tone="warning">
          {s.prompt[going.prompt].title}
          {#snippet action()}
            {#if promptKey && prompting.dismissed === promptKey}
              <Button variant="text" onclick={() => (prompting.dismissed = null)}>{s.prompt.ready}</Button>
            {/if}
          {/snippet}
        </Banner>
      {/if}
      {#if sequences.error}<Banner icon="alert" tone="error">{sequences.error}</Banner>{/if}
      {#if error}
        <Banner icon="alert" tone="error">
          {error}
          {#snippet action()}
            <Button variant="text" onclick={() => (error = "")}>{t.live.dismiss}</Button>
          {/snippet}
        </Banner>
      {/if}
      <div class="actions">
        {#if !going}
          <Button
            variant="primary"
            wide
            busy={busy === "start"}
            disabled={!draft || !!problem || busy !== null || working === "explore"}
            onclick={start}>
            <Icon name="play" size={20} />
            {s.start}
          </Button>
        {:else}
          {#if going.state === "paused" || going.prompt}
            <Button variant="primary" wide busy={busy === "resume"} onclick={() => void act("resume", resumeSequence)}>
              <Icon name="play" size={20} />
              {going.prompt ? s.prompt.ready : t.session.resume}
            </Button>
          {:else if going.state === "pausing"}
            <Button wide busy={busy === "pause"} onclick={() => void act("pause", () => pauseSequence({ now: true }))}>{t.session.pauseNow}</Button>
          {:else}
            <Button wide disabled={going.state !== "running"} busy={busy === "pause"} onclick={() => void act("pause", () => pauseSequence())}>
              <Icon name="pause" size={20} />
              {t.session.pause}
            </Button>
          {/if}
          <Button
            variant="danger"
            wide
            disabled={going.state === "stopping" || going.state === "ending"}
            busy={busy === "stop"}
            onclick={() => (stopping = true)}>
            <Icon name="stop" size={20} />
            {t.session.stop}
          </Button>
        {/if}
      </div>
      {#if !active && sequences.saving}<p class="caption muted outcome">{s.savingDraft}</p>{/if}
    {/snippet}
  </ImageScreen>
{/if}

{#if draft && sheet}
  <SequenceSheets kind={sheet} template={draft} {outputs} canCool={camera?.can_cool ?? false} onclose={() => (sheet = null)} />
{/if}
{#if stopping}
  <StopSheet onstop={stop} onclose={() => (stopping = false)} />
{/if}
{#if focuserSheet}
  <FocuserSheet onclose={() => (focuserSheet = false)} />
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
  .title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: 17px;
    line-height: 24px;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .link {
    color: var(--accent);
    font-size: 15px;
    font-weight: 600;
    text-decoration: none;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  .options {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .options li {
    display: flex;
    align-items: center;
    min-height: 56px;
    border-bottom: 1px solid var(--line);
  }
  .options li > :global(*) {
    flex: 1;
  }
  .option {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    min-height: 56px;
    padding: var(--space-1) 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .option:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .option :global(svg) {
    color: var(--muted);
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    text-align: left;
  }
  .name {
    font-weight: 500;
  }
  .actions {
    display: flex;
    gap: var(--space-2);
  }
  .outcome {
    text-align: center;
  }
</style>
