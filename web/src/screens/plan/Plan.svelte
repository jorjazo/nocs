<script lang="ts">
  // Plan: the targets to take over one night or many, in priority, each with its lines
  // of lights; the run takes the first that is up with frames left, and goes to one
  // that comes first between frames. Explore's base (the image, its histogram and
  // status bar, guiding and focus over it), with the plan's widget where Explore has
  // its go to, and a panel with what the plan does around its targets. Explore,
  // Sequences and Plan exclude each other.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import ImageScreen from "../../components/ImageScreen.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { pauseSequence, resumeSequence, startPlan, stopSequence } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { solvedShown } from "../../lib/explore";
  import { exploreLayout } from "../../lib/explore.svelte";
  import { formatDuration, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { isPlanRun, targetLeft, targetSeconds } from "../../lib/plan";
  import { plan } from "../../lib/plan.svelte";
  import { router } from "../../lib/router.svelte";
  import { currentRow, isActive, workingView } from "../../lib/sequence";
  import {
    coolingSummary,
    endSummary,
    focusSummary,
    groupName,
    outputLabels,
    pointingSummary,
    windowSummary,
  } from "../../lib/sequence.svelte";
  import { stackView, type StackView } from "../../lib/stackview.svelte";
  import FocuserSheet from "../devices/FocuserSheet.svelte";
  import FocusTool from "../explore/FocusTool.svelte";
  import FrameStatus from "../explore/FrameStatus.svelte";
  import GuidingTool from "../explore/GuidingTool.svelte";
  import HistogramBar from "../explore/HistogramBar.svelte";
  import ImageOverlay from "../explore/ImageOverlay.svelte";
  import Viewer from "../explore/Viewer.svelte";
  import SequenceSheets, { type SheetKind } from "../sequence/SequenceSheets.svelte";
  import StopSheet from "../sequence/StopSheet.svelte";
  import PlanTool from "./PlanTool.svelte";

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);

  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const cameras = $derived(live.app.cameras ?? {});
  const preview = $derived(camera?.preview ?? null);
  const guiding = $derived(live.app.guiding ?? null);
  const mount = $derived(live.app.mount ?? null);
  const focuser = $derived(live.app.focuser ?? null);
  const outputs = $derived(live.app.power?.outputs ?? []);
  const livePlan = $derived(live.app.plan ?? null);
  const anyRun = $derived(live.app.sequence?.run ?? null);
  // The plan's run: in progress, or the last one when it was the plan's.
  const run = $derived(isPlanRun(anyRun) ? anyRun : null);
  const going = $derived(isActive(run) ? run : null);
  const active = $derived(going !== null);
  const events = $derived(run ? (live.app.sequence?.events ?? []) : []);
  const working = $derived(workingView(anyRun, live.app.jobs));

  $effect(() => plan.sync(livePlan));
  const draft = $derived(plan.draft);
  const around = $derived(draft?.actions ?? null);
  const editable = $derived(owner && !active && around !== null);
  $effect(() => {
    if (!draft) return;
    void JSON.stringify(draft);
    plan.changed();
  });

  // -- The image -----------------------------------------------------------------

  const stack = $derived(live.app.stack?.current ?? null);
  const groupStack = $derived(stack?.preview ?? null);
  const showStack = $derived(stackView.view === "stack" && groupStack !== null);
  const shown = $derived(showStack ? groupStack : preview);
  const stackStatus = $derived(showStack && stack ? { frames: stack.frames, exposure: stack.exposure } : null);
  const lastSolution = $derived(live.app.solver?.last ?? null);
  const solved = $derived(!showStack && solvedShown(preview, lastSolution) ? lastSolution : null);
  const longitude = $derived.by(() => {
    const sites = live.app.sites;
    const site = sites?.active ? sites.saved[sites.active] : null;
    return site?.longitude ?? mount?.site?.longitude ?? null;
  });

  // The frame in progress, for the widget and the status bar.
  const exposingRow = $derived(going && going.step?.kind === "expose" && camera?.exposing ? currentRow(going) : null);
  const exposing = $derived(
    exposingRow
      ? {
          label: groupName({ frame_type: "light", filter: exposingRow.filter, count: exposingRow.count }, t),
          frame: Math.min(exposingRow.done + 1, exposingRow.count),
          count: exposingRow.count,
          remaining: camera?.remaining ?? null,
          total: exposingRow.exposure ?? camera?.exposure ?? 0,
        }
      : null,
  );
  const status = $derived.by((): { tone: Tone; text: string } | null => {
    if (!going) return null;
    if (exposing && exposing.remaining !== null) {
      const total = formatPlain(exposing.total, locale);
      const elapsed = formatPlain(Math.max(0, Math.floor(exposing.total - exposing.remaining)), locale);
      return { tone: "accent", text: `${exposing.frame}/${exposing.count} · ${t.live.status.exposing(elapsed, total)}` };
    }
    return { tone: going.state === "paused" ? "warning" : "accent", text: t.session.states[going.state === "finished" ? "completed" : going.state] };
  });

  const focuserJob = $derived(holder(live.app.jobs, "focuser"));
  const focuserLocked = $derived(focuserJob !== null && focuserJob.info.kind !== "focus");

  // -- What is left ------------------------------------------------------------------

  const targets = $derived(livePlan?.targets ?? []);
  const left = $derived(targets.reduce((sum, target) => sum + targetLeft(target), 0));
  const seconds = $derived(targets.reduce((sum, target) => sum + targetSeconds(target), 0));

  // -- Actions -----------------------------------------------------------------------

  let busy = $state<"start" | "pause" | "resume" | "stop" | null>(null);
  let error = $state("");
  let stopping = $state(false);
  let sheet = $state<SheetKind | "start" | null>(null);
  let focuserSheet = $state(false);
  let expanded = $state(false);

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
    void act("start", async () => {
      plan.flush();
      await plan.save();
      await startPlan();
    });
  }

  function stop(now: boolean): void {
    stopping = false;
    void act("stop", () => stopSequence({ now, run_end: false }));
  }

  function toggleStartOutput(id: string, on: boolean): void {
    if (!draft) return;
    const now = draft.start_outputs ?? [];
    draft.start_outputs = on ? [...now, id] : now.filter((o) => o !== id);
  }

  const portrait = $derived(exploreLayout.orientation === "portrait");
  const overlays = $derived(exploreLayout.overlays);
  const sheetOpen = $derived(portrait && exploreLayout.open("panel"));
  const canGuide = $derived(!!live.app.equipment?.devices.guide_camera);
  const startOutputs = $derived(draft?.start_outputs ?? []);
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === "Escape" && expanded && !document.querySelector("dialog[open]")) expanded = false;
  }} />

<h1 class="visually-hidden">{p.title}</h1>

{#if !camera}
  <div class="padded">
    <EmptyState icon="plan" title={t.live.noCamera} body={t.live.noCameraBody}>
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
            <PlanTool
              {run}
              plan={livePlan}
              {events}
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
          { value: "stack" as StackView, label: p.showStack },
        ]}
        value={stackView.view}
        onchange={(view) => stackView.set(view)} />
      {#if stackView.view === "stack" && !groupStack}
        <p class="caption muted">{p.stackLater}</p>
      {/if}

      {#if !owner}
        <!-- Observers follow the run in the widget; the settings are the owner's. -->
        <p class="caption muted">{p.ownerOnly}</p>
      {:else if !draft || !around}
        <p class="muted" role="status">{s.loading}</p>
      {:else}
        <div class="title">
          <h2>{targets.length ? p.summary(targets.length, left) : p.empty}</h2>
          <a class="link" href="#/plan/edit">{targets.length ? p.configure : p.addFirst}</a>
        </div>
        {#if seconds > 0}<p class="caption muted">{p.framesLeft(formatDuration(seconds))}</p>{/if}
        {#if active}<p class="caption muted">{p.readOnly}</p>{/if}
        <ul class="options">
          {#if outputs.length}
            <li>
              <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "start")}>
                <span class="text">
                  <span class="name">{p.atStart}</span>
                  <span class="muted small">{startOutputs.length ? p.outputsOn(outputLabels(startOutputs, outputs)) : s.nothing}</span>
                </span>
                <Icon name="chevronRight" />
              </button>
            </li>
          {/if}
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "focus")}>
              <span class="text"><span class="name">{s.autofocus}</span><span class="muted small">{focusSummary(around, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "pointing")}>
              <span class="text"><span class="name">{s.pointing}</span><span class="muted small">{pointingSummary(around, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          <li>
            <Toggle
              label={s.guiding}
              hint={canGuide || around.guide ? s.guidingHint : s.noGuiding}
              checked={around.guide ?? false}
              disabled={!editable || (!canGuide && !around.guide)}
              onchange={(on) => (around.guide = on)} />
          </li>
          <li>
            <Toggle
              label={s.flip}
              hint={around.flip !== false ? s.flipHint(formatPlain(around.flip_after ?? 5, locale)) : s.flipOff}
              checked={around.flip !== false}
              disabled={!editable}
              onchange={(on) => (around.flip = on)} />
          </li>
          {#if around.guide}
            <li>
              <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "dither")}>
                <span class="text">
                  <span class="name">{s.dither}</span>
                  <span class="muted small">
                    {around.dither_every != null ? s.ditherOn(around.dither_every, formatPlain(around.dither_pixels ?? 5, locale)) : s.off}
                  </span>
                </span>
                <Icon name="chevronRight" />
              </button>
            </li>
          {/if}
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "night")}>
              <span class="text"><span class="name">{s.night}</span><span class="muted small">{windowSummary(around, t, locale)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
          {#if camera.can_cool || (around.cooling ?? "off") !== "off"}
            <li>
              <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "cooling")}>
                <span class="text"><span class="name">{s.cooling}</span><span class="muted small">{coolingSummary(around, t, locale)}</span></span>
                <Icon name="chevronRight" />
              </button>
            </li>
          {/if}
          <li>
            <button type="button" class="option" disabled={!editable} onclick={() => (sheet = "end")}>
              <span class="text"><span class="name">{p.whenFinished}</span><span class="muted small">{endSummary(around, t, outputs)}</span></span>
              <Icon name="chevronRight" />
            </button>
          </li>
        </ul>
      {/if}
    {/snippet}
    {#snippet dock()}
      {#if working === "explore" || working === "sequence"}
        <Banner icon={working} tone="warning">
          {working === "explore" ? s.exploreWorking : p.sequenceWorking}
          {#snippet action()}
            <Button variant="text" onclick={() => router.go({ screen: working })}>{working === "explore" ? s.openExplore : p.openSequences}</Button>
          {/snippet}
        </Banner>
      {/if}
      {#if plan.error}<Banner icon="alert" tone="error">{plan.error}</Banner>{/if}
      {#if error}
        <Banner icon="alert" tone="error">
          {error}
          {#snippet action()}
            <Button variant="text" onclick={() => (error = "")}>{t.live.dismiss}</Button>
          {/snippet}
        </Banner>
      {/if}
      <div class="actions" class:hidden={!owner}>
        {#if !going}
          <Button
            variant="primary"
            wide
            busy={busy === "start"}
            disabled={left === 0 || busy !== null || (working !== null && working !== "plan")}
            onclick={start}>
            <Icon name="play" size={20} />
            {p.start}
          </Button>
        {:else}
          {#if going.state === "paused"}
            <Button variant="primary" wide busy={busy === "resume"} onclick={() => void act("resume", resumeSequence)}>
              <Icon name="play" size={20} />
              {t.session.resume}
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
      {#if !going && left === 0 && targets.length}<p class="caption muted outcome">{p.allDone}</p>{/if}
      {#if !active && plan.saving}<p class="caption muted outcome">{s.savingDraft}</p>{/if}
    {/snippet}
  </ImageScreen>
{/if}

{#if around && sheet === "start" && draft}
  <Sheet title={p.atStart} onclose={() => (sheet = null)}>
    <div class="fields">
      <p class="muted">{p.atStartHint}</p>
      {#each outputs as output (output.id)}
        <Toggle
          label={output.label || output.id}
          checked={startOutputs.includes(output.id)}
          onchange={(on) => toggleStartOutput(output.id, on)} />
      {/each}
    </div>
    {#snippet actions()}
      <Button variant="primary" onclick={() => (sheet = null)}>{s.row.done}</Button>
    {/snippet}
  </Sheet>
{:else if around && sheet && sheet !== "start"}
  <SequenceSheets kind={sheet} template={around} {outputs} canCool={camera?.can_cool ?? false} plan onclose={() => (sheet = null)} />
{/if}
{#if stopping}
  <StopSheet plan onstop={(now) => stop(now)} onclose={() => (stopping = false)} />
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
  .fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .fields p {
    margin: 0;
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
  .hidden {
    display: none;
  }
  .outcome {
    text-align: center;
  }
</style>
