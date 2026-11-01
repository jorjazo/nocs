<script lang="ts">
  // The session monitor (stage 5.14): the run in progress or the last one. Its
  // progress, the frame being taken with a countdown, the latest frame with its
  // HFR and stars, the sensor and guiding, the per-filter rows and the events;
  // pause, resume and stop. On a tablet: two columns, the latest frame large
  // with a strip of the recent frames (docs/ux.md §2).
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Icon from "../../components/Icon.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import { pauseSequence, resumeSequence, stopSequence } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration, formatSeconds, formatTime } from "../../lib/format";
  import { guideGraph } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { currentRow, runProgress } from "../../lib/sequence";
  import { describeEvent, describeStep } from "../../lib/sequence.svelte";
  import type { SequenceEvent, SequenceRun } from "../../lib/types";
  import GuideGraph from "../guiding/GuideGraph.svelte";

  let { run }: { run: SequenceRun } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const events = $derived(live.app.sequence?.events ?? []);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const preview = $derived(camera?.preview ?? null);
  const guiding = $derived(live.app.guiding ?? null);
  const stats = $derived(guiding?.stats ?? null);
  const outputs = $derived(live.app.power?.outputs ?? []);

  const progress = $derived(runProgress(run));
  const finished = $derived(run.state === "finished");
  type Shown = keyof typeof t.session.states;
  const shown = $derived<Shown>(run.state === "finished" ? (run.outcome ?? "completed") : run.state);
  const tone = $derived(
    shown === "failed" ? "error" : shown === "paused" || shown === "pausing" || shown === "stopped" ? "warning" : "accent",
  );
  const ends = $derived(
    finished || progress.left === 0 ? null : new Date(Date.now() + progress.left * 1000).toISOString(),
  );
  const target = $derived(Object.values(run.plans)[0]?.target ?? run.name);

  // The frame in progress: the camera exposes for the sequence's plan.
  const exposing = $derived(!finished && run.step?.kind === "expose" && camera?.exposing === true);
  const row = $derived(exposing ? currentRow(run, live.app.filter_wheel?.filter ?? null) : null);
  const remaining = $derived(camera?.remaining ?? null);
  const total = $derived(row?.exposure ?? camera?.exposure ?? 0);
  const elapsed = $derived(remaining !== null && total > 0 ? Math.min(1, Math.max(0, 1 - remaining / total)) : 0);

  const guided = $derived(guiding?.app_state === "Guiding" || (stats?.steps ?? 0) > 0);
  $effect(() => {
    if (guided) guideGraph.start();
  });
  $effect(() => guideGraph.follow(stats));

  let all = $state(false);
  const shownEvents = $derived([...events].reverse().slice(0, all ? events.length : 6));
  // The recent frames for the tablet's strip, newest last.
  const recent = $derived(events.filter((e) => e.kind === "frame").slice(-6));

  let busy: "pause" | "resume" | "stop" | null = $state(null);
  let error = $state("");
  let stopping = $state(false);

  async function act(what: "pause" | "pauseNow" | "resume", call: () => Promise<void>): Promise<void> {
    busy = what === "pauseNow" ? "pause" : what;
    error = "";
    try {
      await call();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  async function stop(now: boolean, runEnd: boolean): Promise<void> {
    stopping = false;
    busy = "stop";
    error = "";
    try {
      await stopSequence({ now, run_end: runEnd });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  function clock(seconds: number): string {
    const s = Math.max(0, Math.ceil(seconds));
    const minutes = Math.floor(s / 60);
    return `${String(minutes).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  // "R 11" and its HFR, from a frame event ("R 120 s 11/15").
  function frameLabel(event: SequenceEvent): [string, string] {
    const words = event.message.split(" ");
    const count = words.at(-1)?.split("/")[0] ?? "";
    const hfr = typeof event.data.hfr === "number" ? formatDecimal(event.data.hfr, locale, 2) : "—";
    return [`${words[0] ?? ""} ${count}`, hfr];
  }
</script>

<section class="monitor" aria-labelledby="session-title">
  <header class="head">
    <div class="titles">
      <span class="muted small">{t.session.since(target, formatTime(run.started, locale))}</span>
      <h2 id="session-title">{run.name}</h2>
    </div>
    <span class="chip {tone}"><span class="dot"></span>{t.session.states[shown]}</span>
    {#if auth.owner && !finished}
      <div class="controls wide-only">
        {#if run.state === "paused"}
          <Button variant="primary" busy={busy === "resume"} onclick={() => void act("resume", resumeSequence)}>{t.session.resume}</Button>
        {:else if run.state === "pausing"}
          <Button busy={busy === "pause"} onclick={() => void act("pauseNow", () => pauseSequence({ now: true }))}>{t.session.pauseNow}</Button>
        {:else}
          <Button disabled={run.state !== "running"} busy={busy === "pause"} onclick={() => void act("pause", () => pauseSequence())}>
            {t.session.pause}
          </Button>
        {/if}
        <Button variant="danger" disabled={run.state === "stopping" || run.state === "ending"} busy={busy === "stop"} onclick={() => (stopping = true)}>
          {t.session.stop}
        </Button>
      </div>
    {/if}
  </header>

  <div class="columns">
    <div class="visual">
      <figure class="latest">
        {#if preview}
          <img src={preview.url} alt={t.session.latest} />
          <figcaption>
            <span class="pill mono">{formatSeconds(preview.exposure, locale)}</span>
            {#if preview.hfr !== null}
              <span class="pill mono">HFR {formatDecimal(preview.hfr, locale, 2)} · {t.session.stars(preview.stars)}</span>
            {/if}
          </figcaption>
        {:else}
          <span class="muted">{t.session.noFrame}</span>
        {/if}
      </figure>
      {#if recent.length}
        <ol class="strip" aria-label={t.session.latest}>
          {#each recent as event, i (event.time + i)}
            {@const [name, hfr] = frameLabel(event)}
            <li class:current={i === recent.length - 1} class="mono"><span>{name}</span><span class="muted">{hfr}</span></li>
          {/each}
        </ol>
      {/if}
    </div>

    <div class="details">
      <div class="progress">
        <div class="line">
          <span class="mono">{t.session.frames(progress.done, progress.total)}</span>
          {#if !finished && progress.left > 0}
            <span class="muted small">
              {t.session.left(formatDuration(progress.left))}{ends ? ` · ${t.session.endsAt(formatTime(ends, locale))}` : ""}
            </span>
          {/if}
        </div>
        <div class="bar" role="progressbar" aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done}>
          <div style:width="{progress.total ? (100 * progress.done) / progress.total : 0}%"></div>
        </div>
      </div>

      {#if !finished}
        <div class="card now">
          {#if preview}<img class="thumb phone-only" src={preview.url} alt={t.session.latest} />{/if}
          <div class="now-text">
            {#if exposing && row}
              <span class="muted small">{t.session.exposing(row.filter ?? "—", Math.min(row.done + 1, row.count), row.count)}</span>
              <span class="countdown mono">{clock(remaining ?? total)}</span>
              <div class="bar thin"><div style:width="{100 * elapsed}%"></div></div>
              <span class="muted small">{t.session.of(formatSeconds(total, locale))}</span>
            {:else if run.state === "running"}
              <span class="muted small">{t.session.states[shown]}</span>
              <span class="step">{describeStep(run, t, locale, outputs)}</span>
            {:else}
              <span class="muted small">{describeStep(run, t, locale, outputs)}</span>
              <span class="step">{t.session.states[shown]}</span>
            {/if}
          </div>
        </div>
      {/if}

      <div class="tiles">
        <div class="card tile">
          <span class="muted small">{t.session.hfr}</span>
          <span class="mono value">{preview?.hfr != null ? formatDecimal(preview.hfr, locale, 2) : "—"}</span>
        </div>
        <div class="card tile">
          <span class="muted small">{t.session.guideRms}</span>
          <span class="mono value">{stats?.rms_total != null ? `${formatDecimal(stats.rms_total, locale, 2)}″` : "—"}</span>
        </div>
        <div class="card tile">
          <span class="muted small">{t.session.sensor}</span>
          <span class="mono value">{camera?.temperature != null ? `${formatDecimal(camera.temperature, locale, 1)}°` : "—"}</span>
        </div>
      </div>

      {#if guided && guideGraph.entries.length}
        <figure class="card graph">
          <figcaption class="small">{t.session.guiding}</figcaption>
          <GuideGraph entries={guideGraph.entries} scale={guiding?.pixel_scale ?? null} units="arcsec" count={60} />
        </figure>
      {/if}

      <section aria-labelledby="per-filter">
        <h3 id="per-filter" class="muted small">{t.session.perFilter}</h3>
        <ul class="rows">
          {#each progress.rows as r, i (i)}
            <li>
              <span class="badge">{r.filter ?? "—"}</span>
              <span class="mono">{r.done} / {r.count}</span>
              <div class="bar thin"><div style:width="{(100 * Math.min(r.done, r.count)) / r.count}%"></div></div>
            </li>
          {/each}
        </ul>
      </section>

      {#if run.restarts > 0}<p class="muted small">{t.session.restarts(run.restarts)}</p>{/if}
      {#if run.error}<Banner icon="alert" tone="error">{run.error}</Banner>{/if}
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

      <section aria-labelledby="events">
        <h3 id="events" class="muted small">{t.session.events}</h3>
        <ol class="events">
          {#each shownEvents as event, i (event.time + event.kind + i)}
            <li>
              <span class="mono muted time">{formatTime(event.time, locale)}</span>
              <span class="dot {event.kind}"></span>
              <span class="small">{describeEvent(event, t, locale)}</span>
            </li>
          {/each}
        </ol>
        {#if events.length > 6}
          <Button variant="text" onclick={() => (all = !all)}>{all ? t.session.fewerEvents : t.session.allEvents}</Button>
        {/if}
      </section>
    </div>
  </div>

  {#if auth.owner && !finished}
    <div class="dock phone-only">
      {#if run.state === "paused"}
        <Button variant="primary" wide busy={busy === "resume"} onclick={() => void act("resume", resumeSequence)}>{t.session.resume}</Button>
      {:else if run.state === "pausing"}
        <Button wide busy={busy === "pause"} onclick={() => void act("pauseNow", () => pauseSequence({ now: true }))}>{t.session.pauseNow}</Button>
      {:else}
        <Button wide disabled={run.state !== "running"} busy={busy === "pause"} onclick={() => void act("pause", () => pauseSequence())}>
          {t.session.pause}
        </Button>
      {/if}
      <Button variant="danger" wide disabled={run.state === "stopping" || run.state === "ending"} busy={busy === "stop"} onclick={() => (stopping = true)}>
        {t.session.stop}
      </Button>
    </div>
  {/if}
</section>

{#if stopping}
  <Sheet title={t.session.stopTitle} onclose={() => (stopping = false)}>
    <div class="choices">
      <button type="button" class="choice" onclick={() => void stop(false, true)}>
        <span class="name">{t.session.stopAfter}</span>
        <span class="muted small">{t.session.stopAfterHint}</span>
      </button>
      <button type="button" class="choice" onclick={() => void stop(true, true)}>
        <span class="name">{t.session.stopNow}</span>
        <span class="muted small">{t.session.stopNowHint}</span>
      </button>
      <button type="button" class="choice" onclick={() => void stop(true, false)}>
        <span class="name">{t.session.stopBare}</span>
        <span class="muted small">{t.session.stopBareHint}</span>
      </button>
    </div>
  </Sheet>
{/if}

<style>
  .monitor {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-top: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: 20px;
    line-height: 28px;
  }
  h3 {
    margin: 0 0 var(--space-1);
    font-weight: 400;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .titles {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 10px;
    border-radius: var(--radius-full);
    background: var(--raised);
    font-size: 13px;
    font-weight: 500;
  }
  .chip .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
  }
  .chip.accent {
    color: var(--accent);
  }
  .chip.warning {
    color: var(--warning);
  }
  .chip.error {
    color: var(--error);
  }
  .controls {
    display: flex;
    gap: var(--space-2);
  }
  .columns {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .visual,
  .wide-only {
    display: none;
  }
  .details {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  .line {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .bar {
    height: 8px;
    margin-top: var(--space-1);
    border-radius: var(--radius-full);
    background: var(--raised);
    overflow: hidden;
  }
  .bar.thin {
    height: 6px;
  }
  .bar > div {
    height: 100%;
    background: var(--accent);
    border-radius: var(--radius-full);
  }
  .now {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-3);
  }
  .thumb {
    flex: none;
    width: 88px;
    height: 88px;
    object-fit: cover;
    border-radius: 10px;
    background: #000;
  }
  .now-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .countdown {
    font-size: 28px;
    line-height: 32px;
    font-weight: 500;
  }
  .step {
    font-size: 17px;
    line-height: 24px;
    font-weight: 500;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .tile {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
  }
  .value {
    font-size: 20px;
    line-height: 26px;
  }
  .graph {
    margin: 0;
    padding: var(--space-2) var(--space-3);
  }
  .rows,
  .events {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li {
    display: grid;
    grid-template-columns: 56px 80px 1fr;
    align-items: center;
    gap: var(--space-2);
    min-height: 36px;
  }
  .rows .bar {
    margin-top: 0;
  }
  .badge {
    height: 24px;
    display: grid;
    place-items: center;
    border-radius: 8px;
    background: var(--raised);
    font-size: 13px;
    font-weight: 600;
  }
  .events li {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 36px;
    border-bottom: 1px solid var(--line);
  }
  .time {
    flex: none;
    min-width: 44px;
    font-size: 13px;
    white-space: nowrap;
  }
  .events .dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--line);
  }
  .events .dot.frame,
  .events .dot.action {
    background: var(--muted);
  }
  .events .dot.trigger,
  .events .dot.started,
  .events .dot.resumed {
    background: var(--accent);
  }
  .events .dot.failed {
    background: var(--error);
  }
  .events .dot.recovery,
  .events .dot.skipped,
  .events .dot.paused,
  .events .dot.condition {
    background: var(--warning);
  }
  .dock {
    position: sticky;
    bottom: calc(var(--tabbar-height) + env(safe-area-inset-bottom) + var(--space-2));
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
    padding-top: var(--space-2);
    background: var(--bg);
  }
  .choices {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .choice {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    min-height: 60px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .choice .name {
    font-weight: 500;
  }
  .latest {
    position: relative;
    margin: 0;
    display: grid;
    place-items: center;
    aspect-ratio: 3 / 2;
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: #000;
    overflow: hidden;
  }
  .latest img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .latest figcaption {
    position: absolute;
    left: var(--space-3);
    bottom: var(--space-3);
    display: flex;
    gap: var(--space-2);
  }
  .pill {
    padding: 4px 10px;
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--bg) 80%, transparent);
    font-size: 13px;
  }
  .strip {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .strip li {
    display: flex;
    flex-direction: column;
    padding: var(--space-2);
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--surface);
    font-size: 12px;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .strip li.current {
    border-color: var(--accent);
  }
  /* Tablets: the latest frame large on the left, everything else on the right. */
  @media (min-width: 1000px) {
    .columns {
      display: grid;
      grid-template-columns: minmax(0, 3fr) minmax(320px, 2fr);
      gap: var(--space-6);
      align-items: start;
    }
    .visual {
      display: block;
      position: sticky;
      top: var(--space-4);
    }
    .wide-only {
      display: flex;
    }
    .phone-only {
      display: none;
    }
  }
</style>
