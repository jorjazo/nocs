<script lang="ts">
  // A target's page: a catalog object to add to the plan (#/plan/object/<id>), a
  // point from coordinates or a saved frame (#/plan/new), or one of the plan's own
  // (#/plan/target/<id>). What it is, its altitude tonight over the site's horizon,
  // the framing chart with the main camera's frame (dragging it frames off the
  // object; the plan points where the frame does, at its angle), its lines of
  // lights, and Go and centre. A target of the plan saves its changes as they are
  // made.
  import { untrack } from "svelte";
  import AltitudeChart from "../../components/AltitudeChart.svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import SkyChart, { type OwnFrame } from "../../components/SkyChart.svelte";
  import TextField from "../../components/TextField.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import {
    ApiError,
    centerOn,
    getSolvedFrames,
    getTarget,
    getVisibility,
    gotoMount,
    resetPlanTarget,
    setTarget,
    solveSavedFrame,
  } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration, formatTime } from "../../lib/format";
  import { goRefusal } from "../../lib/goto";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa, mountActivity } from "../../lib/mount.svelte";
  import { newId, newLine, planIds, targetSeconds } from "../../lib/plan";
  import { clearPending, getPending, plan } from "../../lib/plan.svelte";
  import { prefs } from "../../lib/prefs.svelte";
  import { href, router } from "../../lib/router.svelte";
  import { separation, type Sky } from "../../lib/sky/projection";
  import { commonNames, objectSummary } from "../../lib/targets";
  import { siteKey, tonight } from "../../lib/tonight.svelte";
  import type { CatalogObject, PlanTarget, SolvedFrames, TargetVisibility } from "../../lib/types";
  import CenteringCard from "../explore/CenteringCard.svelte";
  import SunWarning from "../devices/SunWarning.svelte";
  import LinesEditor from "./LinesEditor.svelte";

  // One of: a catalog object's id, a plan target's id, or neither (coordinates).
  let { object: objectId = null, target: targetId = null }: { object?: string | null; target?: string | null } = $props();

  const t = $derived(i18n.t);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);
  const owner = $derived(auth.owner);
  const almanac = $derived(tonight.almanac);
  const mount = $derived(live.app.mount ?? null);

  $effect(() => plan.sync(live.app.plan ?? null));
  $effect(() => {
    if (!plan.draft) return;
    void JSON.stringify(plan.draft);
    plan.changed();
  });
  $effect(() => {
    void tonight.load(siteKey(live.app.sites));
  });

  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 60_000);
    return () => clearInterval(timer);
  });

  // -- What the page is about -----------------------------------------------------------

  // The plan's own target, edited in place (and saved a moment later).
  const existing = $derived(targetId ? ((plan.draft?.targets ?? []).find((each) => each.id === targetId) ?? null) : null);
  // A target to add: built here, and put in the plan by Add.
  let fresh = $state<PlanTarget | null>(null);
  const entry = $derived(existing ?? fresh);
  const catalogId = $derived(objectId ?? existing?.object ?? null);
  // Another target of the plan already on this object.
  const already = $derived(objectId ? ((plan.draft?.targets ?? []).find((each) => each.object === objectId) ?? null) : null);

  let object = $state<CatalogObject | null>(null);
  // A plan target's catalog object that could not be had.
  let unknown = $state(false);
  let missing = $state(false);
  let failed = $state("");
  let seen = $state<TargetVisibility | null>(null);
  let unseen = $state(false);
  const minAltitude = $derived(plan.draft?.actions?.min_altitude ?? 30);

  function freshTarget(name: string, ra: number, dec: number, rotation: number | null, catalog: string | null): PlanTarget {
    const taken = plan.draft ? planIds(plan.draft) : [];
    const id = newId(taken);
    const camera = live.app.cameras?.main_camera ?? null;
    const filters = (live.app.filter_wheel?.names ?? []).filter((name) => name);
    const line = newLine([], filters, newId([...taken, id]), { gain: camera?.gain ?? null, offset: camera?.offset ?? null });
    return { id, name, object: catalog, ra, dec, rotation, lines: [line] };
  }

  // The catalog object, when the target is one.
  $effect(() => {
    const designation = catalogId;
    object = null;
    missing = false;
    unknown = false;
    failed = "";
    if (!designation) return;
    getTarget(designation)
      .then((found) => {
        if (designation !== catalogId) return;
        object = found;
        if (objectId && !fresh) {
          const rotation = initialRotation();
          fresh = freshTarget(found.label, found.ra, found.dec, rotation, found.id);
          center = { ra: found.ra, dec: found.dec };
          rotation_ = rotation;
          framed = true;
        }
      })
      .catch((e) => {
        if (designation !== catalogId) return;
        // A plan target carries its own position: only its names are missing then.
        if (!objectId) unknown = true;
        else if (e instanceof ApiError && e.status === 404) missing = true;
        else failed = errorText(e, t);
      });
  });

  // A point from coordinates or a saved frame, waiting since #/plan/add.
  $effect(() => {
    if (objectId || targetId || fresh) return;
    const point = untrack(() => getPending());
    if (!point) {
      missing = true;
      return;
    }
    fresh = freshTarget(point.name, point.ra, point.dec, point.rotation, null);
    center = { ra: point.ra, dec: point.dec };
    rotation_ = point.rotation === null ? initialRotation() : Math.round(point.rotation) % 360;
    framed = true;
  });

  // A plan target opens on its own framing.
  let opened = false;
  $effect(() => {
    if (!existing || opened) return;
    opened = true;
    untrack(() => {
      center = { ra: existing.ra, dec: existing.dec };
      rotation_ = existing.rotation == null ? initialRotation() : Math.round(existing.rotation) % 360;
      framed = true;
    });
  });

  // Where the object is (the frame may be off it): the catalog's, or where the point was.
  const anchor = $derived.by((): Sky | null => {
    if (object) return { ra: object.ra, dec: object.dec };
    return entry ? { ra: entryAnchor?.ra ?? entry.ra, dec: entryAnchor?.dec ?? entry.dec } : null;
  });
  // A point without an object is anchored where it was first.
  let entryAnchor = $state<Sky | null>(null);
  $effect(() => {
    if (entry && !entryAnchor && !catalogId) entryAnchor = { ra: entry.ra, dec: entry.dec };
  });

  const visibilityKey = $derived(catalogId ?? (anchor ? `${anchor.ra},${anchor.dec}` : null));
  $effect(() => {
    const key = visibilityKey;
    const minimum = minAltitude;
    seen = null;
    unseen = false;
    if (!key) return;
    getVisibility([key], minimum)
      .then((v) => {
        if (key === visibilityKey) seen = v.targets[0] ?? null;
      })
      .catch(() => {
        if (key === visibilityKey) unseen = true;
      });
  });

  // -- Framing ------------------------------------------------------------------------

  function initialRotation(): number {
    // The camera as it is: the angle of the last solved frame.
    const last = live.app.solver?.last?.rotation;
    return last === undefined || last === null ? 0 : Math.round(last) % 360;
  }

  let center: Sky = $state({ ra: 0, dec: 0 });
  let rotation_ = $state(0);
  // The chart starts on the target's own framing, before it frames the target.
  let framed = $state(false);
  // A target without an angle keeps none until the slider moves.
  let firstRotation: number | null = null;
  // The framing is the target's: where the plan points, at that angle.
  $effect(() => {
    const target = entry;
    const c = center;
    const r = rotation_;
    if (!target || !framed) return;
    untrack(() => {
      if (Math.abs(target.ra - c.ra) > 1e-7 || Math.abs(target.dec - c.dec) > 1e-7) {
        target.ra = c.ra;
        target.dec = c.dec;
      }
      if (firstRotation === null) firstRotation = r;
      if (target.rotation !== r && (target.rotation != null || r !== firstRotation)) target.rotation = r;
    });
  });

  const field = $derived(live.app.cameras?.main_camera?.field ?? null);
  const span = $derived(field ? Math.max(1, Math.max(field.width, field.height) * 2.2) : 4);
  const offset = $derived(anchor ? separation(center, anchor) * 60 : 0);
  const moved = $derived(offset > 0.5);
  const last = $derived(live.app.solver?.last ?? null);
  const solved = $derived(
    last ? { ra: last.ra, dec: last.dec, width: last.fov[0] ?? 0, height: last.fov[1] ?? 0, rotation: last.rotation } : null,
  );
  const turn = $derived(last ? ((((rotation_ - last.rotation) % 360) + 540) % 360) - 180 : null);

  // -- The user's own frames (3.7c) ---------------------------------------------------

  let mine = $state<SolvedFrames | null>(null);
  let solveJob = $state<string | null>(null);
  let solveError = $state("");
  const mineRadius = $derived(Math.min(30, Math.max(3, span)));

  async function loadMine(where: Sky, radius: number, label: string | undefined): Promise<void> {
    try {
      const found = await getSolvedFrames(where.ra, where.dec, radius, label);
      if (anchor && separation(anchor, where) < 1e-6) mine = found;
    } catch {
      if (anchor && separation(anchor, where) < 1e-6) mine = null;
    }
  }

  $effect(() => {
    const where = anchor;
    const radius = mineRadius;
    const label = object?.label ?? entry?.name;
    mine = null;
    if (where && owner) void untrack(() => loadMine(where, radius, label));
  });

  const ownFrames: OwnFrame[] = $derived(
    prefs.ownFrames && mine
      ? mine.frames.flatMap((f) =>
          f.image
            ? [{ image: f.image, ra: f.ra, dec: f.dec, width: f.fov[0] ?? 0, height: f.fov[1] ?? 0, rotation: f.rotation, mirrored: f.mirrored }]
            : [],
        )
      : [],
  );

  async function solveMine(): Promise<void> {
    const candidate = mine?.candidate;
    if (candidate === null || candidate === undefined) return;
    solveError = "";
    try {
      solveJob = await solveSavedFrame(candidate);
    } catch (e) {
      solveError = errorText(e, t);
    }
  }

  const solving = $derived(solveJob ? (live.app.jobs?.[solveJob] ?? null) : null);
  $effect(() => {
    const job = solving;
    if (!job || job.state === "running") return;
    untrack(() => {
      if (job.state === "failed") solveError = job.error ?? t.plan.solveFailed;
      solveJob = null;
      if (anchor) void loadMine(anchor, mineRadius, object?.label ?? entry?.name);
    });
  });

  // -- Actions ------------------------------------------------------------------------

  let busy = $state<string | null>(null);
  let error = $state("");
  type Go = "goto" | "center";
  type Guiding = "resume" | "stop" | undefined;
  let refused = $state<{ kind: Go; guiding: Guiding } | null>(null);
  let guidingRefused = $state<Go | null>(null);
  let nearSun = $state<(() => void) | null>(null);

  const mountJob = $derived(holder(live.app.jobs, "mount"));
  const goReason = $derived.by((): string | null => {
    if (!owner) return t.plan.ownerOnly;
    if (!mount) return t.plan.noMount;
    if (mount.parked) return t.plan.parked;
    if (mountJob) return mountJob.info.kind === "goto" || mountJob.info.kind === "center" ? t.plan.mountGoing : t.plan.mountBusy;
    return null;
  });
  const centerReason = $derived.by((): string | null => {
    if (goReason) return goReason;
    if (!live.app.solver?.available) return t.center.noSolver;
    if (!live.app.cameras?.main_camera) return t.center.noCamera;
    if (holder(live.app.jobs, "main_camera")) return t.center.cameraBusy;
    return null;
  });

  function add(): void {
    const draft = plan.draft;
    const target = fresh;
    if (!draft || !target) return;
    draft.targets = [...(draft.targets ?? []), $state.snapshot(target)];
    void plan.save();
    // Back here must not offer the same point again.
    if (!objectId) clearPending();
    router.go({ screen: "plan-target", id: target.id });
  }

  function remove(): void {
    const draft = plan.draft;
    if (!draft || !existing) return;
    draft.targets = (draft.targets ?? []).filter((each) => each.id !== existing.id);
    void plan.save();
    router.go({ screen: "plan-edit" });
  }

  async function reset(): Promise<void> {
    if (!existing) return;
    try {
      await plan.save();
      await resetPlanTarget(existing.id);
    } catch (e) {
      error = errorText(e, t);
    }
  }

  async function go(kind: Go, force = false, guiding: Guiding = undefined): Promise<void> {
    if (!entry) return;
    busy = guiding ? `${kind}:${guiding}` : kind;
    error = "";
    refused = null;
    guidingRefused = null;
    const body = {
      ra: center.ra,
      dec: center.dec,
      force,
      stop_guiding: guiding === "stop",
      resume_guiding: guiding === "resume",
    };
    try {
      if (kind === "center") await centerOn(body);
      else await gotoMount({ frame: "j2000", ...body });
      // Explore's lights are named after it (Light/M_42/), and their OBJECT header.
      await setTarget(entry.name);
    } catch (e) {
      const why = e instanceof ApiError ? goRefusal(e.status, e.message) : null;
      if (why === "horizon") refused = { kind, guiding };
      else if (why === "guiding") guidingRefused = kind;
      else if (why === "sun") nearSun = () => void go(kind, force, guiding);
      else error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  const centering = $derived.by(() => {
    const c = live.app.centering ?? null;
    if (!c || !anchor) return null;
    return separation(c.target, center) * 60 < 1 || separation(c.target, anchor) * 60 < 1 ? c : null;
  });
  const activity = $derived(mount ? mountActivity(mount, t) : null);
  const names = $derived(object ? commonNames(object, locale) : []);
  const title = $derived(names[0] ?? object?.label ?? entry?.name ?? "");
  const running = $derived(live.app.sequence?.run?.sequence === "plan" && live.app.sequence.run.state !== "finished");
</script>

<div class="page">
  <a class="back" href={href({ screen: existing ? "plan-edit" : "plan-add" })}><Icon name="chevronLeft" />{existing ? p.targetsTitle : p.addTitle}</a>

  {#if targetId && plan.draft && !existing}
    <EmptyState icon="plan" title={p.gone} body={p.goneBody} />
  {:else if missing}
    <EmptyState icon="plan" title={t.plan.missing} body={objectId ? t.plan.missingBody(objectId) : p.noPoint} />
  {:else if failed}
    <Banner icon="alert" tone="error">{failed}</Banner>
  {:else if !entry || (catalogId && !object && !unknown)}
    <p class="muted" role="status">{t.plan.loading}</p>
  {:else}
    <header class="title">
      {#if object}
        <span class="eyebrow muted">{object.label}{object.label !== object.id ? ` · ${object.id}` : ""}</span>
      {/if}
      <h1>{title}</h1>
      {#if object}<p class="summary muted">{objectSummary(object, t, locale)}</p>{/if}
      <p class="coordinates muted mono">{formatRa(entry.ra)} · {formatDec(entry.dec)}</p>
    </header>

    {#if already && !existing}
      <Banner icon="plan">
        {p.already}
        {#snippet action()}
          <Button variant="text" onclick={() => router.go({ screen: "plan-target", id: already.id })}>{p.openIt}</Button>
        {/snippet}
      </Banner>
    {/if}

    {#if !object}
      <TextField label={p.name} hint={p.nameHint} bind:value={entry.name} />
    {/if}

    <section class="card" aria-labelledby="lines-title">
      <div class="row">
        <h2 id="lines-title">{p.lines}</h2>
        {#if targetSeconds(entry) > 0}<span class="muted small">{p.framesLeft(formatDuration(targetSeconds(entry)))}</span>{/if}
      </div>
      <LinesEditor target={entry} disabled={!owner} />
    </section>

    <section class="card" aria-labelledby="tonight-title">
      <div class="row">
        <h2 id="tonight-title">{t.plan.tonight}</h2>
        {#if seen}
          <Chip tone={seen.observable > 0 ? "ok" : "neutral"}>
            {seen.observable > 0 ? t.plan.upFor(formatDuration(seen.observable)) : seen.above_horizon > 0 ? t.plan.lowTonight : t.plan.notUp}
          </Chip>
        {/if}
      </div>
      {#if seen && almanac && almanac.times.length === seen.altitude.length}
        <AltitudeChart
          times={almanac.times}
          sunAltitude={almanac.sun_altitude}
          altitude={seen.altitude}
          horizon={seen.horizon}
          moon={almanac.moon.altitude}
          {minAltitude}
          {now} />
        <p class="legend muted">{t.plan.legend(minAltitude)}</p>
        <div class="facts">
          <div>
            <span class="label muted">{t.plan.transit}</span>
            <span class="readout">{seen.transit ? formatTime(seen.transit, locale) : "—"}</span>
            <span class="muted">{t.plan.at(formatDecimal(seen.transit_altitude, locale, 0))}</span>
          </div>
          <div>
            <span class="label muted">{t.plan.best}</span>
            <span class="readout">{seen.best ? `${formatTime(seen.best.start, locale)}–${formatTime(seen.best.end, locale)}` : "—"}</span>
            <span class="muted">{t.plan.aboveMinimum(minAltitude)}</span>
          </div>
          <div>
            <span class="label muted">{t.plan.moon}</span>
            <span class="readout">{formatDecimal(seen.moon_separation, locale, 0)}°</span>
            <span class="muted">{t.tonight.lit(formatDecimal(almanac.moon.fraction * 100, locale, 0))}</span>
          </div>
        </div>
      {:else if tonight.missingSite}
        <p class="muted">{t.tonight.noSite}</p>
      {:else if unseen}
        <p class="muted">{p.noVisibility}</p>
      {:else}
        <p class="muted" role="status">{t.tonight.loading}</p>
      {/if}
    </section>

    <section class="card framing" aria-labelledby="framing-title">
      <div class="row">
        <h2 id="framing-title">{t.plan.framing}</h2>
      </div>
      {#if !field}<p class="muted">{t.plan.noField}</p>{/if}
      <div class="chart">
        {#if anchor}
          {#key catalogId ?? entry.id}
            <SkyChart
              target={anchor}
              bind:center
              {span}
              {field}
              rotation={rotation_}
              {solved}
              survey={prefs.survey}
              frames={ownFrames}
              highlight={object?.id} />
          {/key}
        {/if}
      </div>
      <p class="caption muted">
        {#if moved}
          {t.plan.moved(formatDecimal(offset, locale, offset < 10 ? 1 : 0))}
          <button type="button" class="link" onclick={() => anchor && (center = { ...anchor })}>{t.plan.recenter}</button>
        {:else}
          {t.plan.chartHint}
        {/if}
      </p>
      <label class="rotation">
        <span class="label muted">{t.plan.rotation} <span class="mono">{rotation_}°</span></span>
        <input type="range" min="0" max="359" step="1" bind:value={rotation_} />
        <span class="caption muted">{t.plan.rotationHint}</span>
      </label>
      {#if last && turn !== null}
        <div class="turn">
          <p class="caption">
            {Math.abs(turn) < 1
              ? t.plan.turnDone(formatDecimal(last.rotation % 360, locale, 0))
              : t.plan.turn(
                  formatDecimal(Math.abs(turn), locale, 0),
                  formatDecimal(last.rotation % 360, locale, 0),
                  formatDecimal(rotation_, locale, 0),
                )}
          </p>
          <Button variant="text" onclick={() => (rotation_ = Math.round(last.rotation) % 360)}>{t.plan.useCamera}</Button>
        </div>
      {/if}
      {#if mine && mine.frames.length}
        <Toggle
          label={t.plan.ownFrames}
          hint={t.plan.ownFramesHint(mine.frames.length)}
          checked={prefs.ownFrames}
          onchange={(on) => prefs.setOwnFrames(on)} />
      {/if}
      {#if mine && mine.unsolved}
        <div class="turn">
          <p class="caption">
            {solveJob ? t.plan.solvingOne : mine.candidate === null ? t.plan.unsolvedUnplugged(entry.name) : t.plan.unsolved(mine.unsolved, entry.name)}
          </p>
          <Button
            variant="text"
            disabled={mine.candidate === null || !live.app.solver?.available}
            busy={solveJob !== null}
            onclick={() => void solveMine()}>{t.plan.solveOne}</Button>
        </div>
      {/if}
      {#if solveError}<Banner icon="alert" tone="error">{solveError}</Banner>{/if}
      <Toggle label={t.plan.survey} hint={t.plan.surveyHint} checked={prefs.survey} onchange={(on) => prefs.setSurvey(on)} />
    </section>

    <section class="card actions" aria-label={t.plan.actions}>
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      {#if plan.error}<Banner icon="alert" tone="error">{plan.error}</Banner>{/if}
      {#if refused}
        <Banner icon="alert" tone="warning">
          {t.mount.belowHorizon}
          {#snippet action()}
            <ConfirmButton label={t.mount.goAnyway} confirmLabel={t.mount.goAnywayConfirm} onconfirm={() => refused && void go(refused.kind, true, refused.guiding)} />
          {/snippet}
        </Banner>
      {/if}
      {#if guidingRefused}
        {@const kind = guidingRefused}
        <Banner icon="alert" tone="warning">{kind === "center" ? t.plan.guidingRefusedCenter : t.plan.guidingRefused}</Banner>
        <div class="buttons">
          <Button variant="primary" disabled={goReason !== null} busy={busy === `${kind}:resume`} onclick={() => void go(kind, false, "resume")}>
            {t.plan.goResumeGuiding}
          </Button>
          <Button disabled={goReason !== null} busy={busy === `${kind}:stop`} onclick={() => void go(kind, false, "stop")}>{t.plan.goStopGuiding}</Button>
        </div>
      {/if}
      <div class="buttons">
        {#if !existing}
          <Button variant="primary" disabled={!owner || !plan.draft || !entry.name.trim()} onclick={add}>
            <Icon name="plus" size={20} />{p.add}
          </Button>
        {/if}
        <Button variant={existing ? "primary" : "secondary"} disabled={centerReason !== null || running} busy={busy === "center"} onclick={() => void go("center")}>
          {t.center.goCenter}
        </Button>
        <Button disabled={goReason !== null || running} busy={busy === "goto"} onclick={() => void go("goto")}>{t.mount.go}</Button>
      </div>
      <p class="caption muted">{running ? p.planRuns : (centerReason ?? goReason ?? (moved ? t.plan.goesToFrame : t.plan.goHint))}</p>
      {#if activity?.moving}<p class="caption" role="status">{activity.text}</p>{/if}
      {#if centering}<CenteringCard {centering} />{/if}
      {#if existing && owner}
        <div class="buttons">
          <ConfirmButton label={p.reset} confirmLabel={p.resetConfirm} onconfirm={() => void reset()} />
          <ConfirmButton label={p.remove} confirmLabel={p.removeConfirm} onconfirm={remove} />
        </div>
      {/if}
    </section>
  {/if}
</div>

{#if nearSun}
  <SunWarning
    onclose={() => (nearSun = null)}
    onacknowledged={() => {
      const again = nearSun;
      nearSun = null;
      again?.();
    }} />
{/if}

<style>
  .page {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding-top: var(--space-2);
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    color: var(--accent);
    text-decoration: none;
    align-self: flex-start;
  }
  .title {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h1 {
    margin: 0;
    font-size: 28px;
    line-height: 34px;
  }
  h2,
  p {
    margin: 0;
  }
  .summary {
    font-size: 15px;
    line-height: 20px;
  }
  .coordinates {
    font-size: 13px;
    line-height: 18px;
  }
  .eyebrow,
  .label,
  .caption,
  .legend,
  .small {
    font-size: 12px;
    line-height: 16px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3);
  }
  .facts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .readout {
    font-size: 18px;
    line-height: 24px;
  }
  .chart {
    height: min(60dvh, 520px);
    min-height: 320px;
    margin: 0 calc(-1 * var(--space-4));
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
  .rotation {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .rotation input {
    min-height: var(--touch);
    accent-color: var(--accent);
  }
  .turn {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .link {
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  @media (min-width: 420px) {
    .chart {
      margin: 0 calc(-1 * var(--space-6));
    }
  }
</style>
