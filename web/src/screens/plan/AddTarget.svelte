<script lang="ts">
  // Add a target to the plan (#/plan/add): a catalog object found by name, in either
  // language and without accents, with how long it is up in the dark tonight; a point
  // from its coordinates; or where one of the lights NOCS saved points, solved with the
  // scale its headers give. Each leads to the target's page, where it is added.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import TextField from "../../components/TextField.svelte";
  import { getFrames, getNights, getVisibility, searchTargets, solveSavedFrame } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { parseDec, parseRa } from "../../lib/plan";
  import { setPending } from "../../lib/plan.svelte";
  import { href, router } from "../../lib/router.svelte";
  import { objectName, objectSummary } from "../../lib/targets";
  import type { CatalogMatch, NightGroup, NightInfo, TargetVisibility } from "../../lib/types";

  const t = $derived(i18n.t);
  const p = $derived(t.planView);
  const locale = $derived(i18n.locale);

  type Way = "catalog" | "coordinates" | "frame";
  let way = $state<Way>("catalog");

  // -- The catalog ----------------------------------------------------------------------

  // The search survives going to a target and back.
  let query = $state(sessionQuery());
  let matches: CatalogMatch[] = $state([]);
  let seen: Partial<Record<string, TargetVisibility>> = $state({});
  let searched = $state(false);
  let error = $state("");

  function sessionQuery(): string {
    try {
      return sessionStorage.getItem("nocs.plan.query") ?? "";
    } catch {
      return "";
    }
  }

  let seq = 0;
  $effect(() => {
    const text = query.trim();
    try {
      sessionStorage.setItem("nocs.plan.query", query);
    } catch {
      // Private mode: the search is just not kept.
    }
    const id = ++seq;
    if (!text) {
      matches = [];
      searched = false;
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const found = await searchTargets(text, 20);
        if (id !== seq) return;
        matches = found;
        searched = true;
        error = "";
        if (found.length) {
          // How each result does tonight; without a site there is simply no column.
          const v = await getVisibility(found.map((m) => `${m.object.ra},${m.object.dec}`)).catch(() => null);
          if (id === seq && v) {
            seen = Object.fromEntries(v.targets.flatMap((target, i) => (found[i] ? [[found[i].object.id, target]] : [])));
          }
        }
      } catch (e) {
        if (id === seq) error = errorText(e, t);
      }
    }, 200);
    return () => clearTimeout(timer);
  });

  // The phase's exit targets, to start from.
  const SUGGESTIONS = ["NGC 292", "NGC 253", "NGC 104", "NGC 5139", "NGC 3372", "M 42"];

  function upTonight(id: string): string | null {
    const v = seen[id];
    if (!v) return null;
    if (v.observable > 0) return t.plan.upFor(formatDuration(v.observable));
    return v.above_horizon > 0 ? t.plan.lowTonight : t.plan.notUp;
  }

  // -- Coordinates ----------------------------------------------------------------------

  let name = $state("");
  let raText = $state("");
  let decText = $state("");
  const ra = $derived(parseRa(raText));
  const dec = $derived(parseDec(decText));

  function fromCoordinates(): void {
    if (ra === null || dec === null) return;
    setPending({ name: name.trim() || p.untitled, ra, dec, rotation: null });
    router.go({ screen: "plan-new" });
  }

  // -- One of my frames -------------------------------------------------------------------

  let nights = $state<NightInfo[] | null>(null);
  let night = $state<number | null>(null);
  let solving = $state<{ job: string; name: string } | null>(null);
  let frameError = $state("");

  $effect(() => {
    if (way !== "frame" || nights !== null) return;
    getNights()
      .then((found) => {
        nights = found;
        night = found[0]?.id ?? null;
      })
      .catch((e) => (frameError = errorText(e, t)));
  });

  const lights = $derived(
    (nights ?? []).find((n) => n.id === night)?.groups.filter((g) => g.frame_type === "light") ?? [],
  );

  async function solveGroup(group: NightGroup): Promise<void> {
    if (night === null) return;
    frameError = "";
    try {
      const frames = await getFrames({
        night,
        type: "light",
        target: group.target ?? undefined,
        filter: group.filter ?? undefined,
        limit: 20,
      });
      // The one with the most stars, on a drive that is plugged in.
      const best = frames.filter((f) => f.available).sort((a, b) => (b.stars ?? 0) - (a.stars ?? 0))[0];
      if (!best) {
        frameError = p.frameUnavailable;
        return;
      }
      solving = { job: await solveSavedFrame(best.id), name: group.target ?? p.untitled };
    } catch (e) {
      frameError = errorText(e, t);
    }
  }

  // When the solve ends: its centre and angle make the new target, or what failed.
  const job = $derived(solving ? (live.app.jobs?.[solving.job] ?? null) : null);
  $effect(() => {
    const done = job;
    const asked = solving;
    if (!done || !asked || done.state === "running") return;
    solving = null;
    const result = done.result as { ra?: unknown; dec?: unknown; rotation?: unknown } | null;
    if (done.state !== "succeeded" || typeof result?.ra !== "number" || typeof result.dec !== "number") {
      frameError = done.error ?? t.plan.solveFailed;
      return;
    }
    const rotation = typeof result.rotation === "number" ? ((result.rotation % 360) + 360) % 360 : null;
    setPending({ name: asked.name, ra: result.ra, dec: result.dec, rotation });
    router.go({ screen: "plan-new" });
  });
</script>

<div class="page">
  <a class="back" href={href({ screen: "plan-edit" })}><Icon name="chevronLeft" />{p.targetsTitle}</a>
  <header class="title">
    <h1>{p.addTitle}</h1>
  </header>

  <SegmentedControl
    label={p.addTitle}
    options={[
      { value: "catalog" as Way, label: p.fromCatalog },
      { value: "coordinates" as Way, label: p.fromCoordinates },
      { value: "frame" as Way, label: p.fromFrame },
    ]}
    value={way}
    onchange={(value) => (way = value)} />

  {#if way === "catalog"}
    <section class="search" aria-label={t.plan.search}>
      <TextField label={t.plan.search} hint={t.plan.searchHint} bind:value={query} />
      {#if !query.trim()}
        <div class="suggestions">
          {#each SUGGESTIONS as suggestion (suggestion)}
            <button type="button" class="suggestion" onclick={() => (query = suggestion)}>{suggestion}</button>
          {/each}
        </div>
      {/if}
      {#if error}<p class="error">{error}</p>{/if}
      {#if matches.length}
        <ul class="results">
          {#each matches as match (match.object.id)}
            {@const object = match.object}
            {@const up = upTonight(object.id)}
            <li>
              <a href={href({ screen: "target", id: object.id })}>
                <span class="text">
                  <span class="name">{objectName(object, locale)}</span>
                  <span class="muted">{objectSummary(object, t, locale)}</span>
                </span>
                {#if up}
                  {@const v = seen[object.id]}
                  <span class="up" class:muted={!v?.observable}>
                    {up}
                    {#if v?.observable}
                      <span class="muted">{t.plan.peak(formatDecimal(v.transit_altitude, locale, 0))}</span>
                    {/if}
                  </span>
                {/if}
                <Icon name="chevronRight" />
              </a>
            </li>
          {/each}
        </ul>
      {:else if searched && query.trim()}
        <p class="muted">{t.plan.noMatch}</p>
      {/if}
      <p class="credit muted">{t.plan.credit}</p>
    </section>
  {:else if way === "coordinates"}
    <section class="form" aria-label={p.fromCoordinates}>
      <TextField label={p.name} hint={p.nameHint} bind:value={name} />
      <TextField label={p.ra} hint={raText && ra === null ? p.raInvalid : p.raHint} bind:value={raText} />
      <TextField label={p.dec} hint={decText && dec === null ? p.decInvalid : p.decHint} bind:value={decText} />
      <Button variant="primary" disabled={ra === null || dec === null} onclick={fromCoordinates}>{p.next}</Button>
    </section>
  {:else}
    <section class="form" aria-label={p.fromFrame}>
      <p class="muted">{p.fromFrameHint}</p>
      {#if frameError}<Banner icon="alert" tone="error">{frameError}</Banner>{/if}
      {#if nights === null}
        <p class="muted" role="status">{t.plan.loading}</p>
      {:else if !nights.length}
        <p class="muted">{p.noFrames}</p>
      {:else}
        <label class="field">
          <span class="label muted">{p.night}</span>
          <select bind:value={night}>
            {#each nights as each (each.id)}
              <option value={each.id}>{each.night}{each.site ? ` · ${each.site}` : ""}</option>
            {/each}
          </select>
        </label>
        {#if lights.length}
          <ul class="results">
            {#each lights as group, i (i)}
              <li>
                <button type="button" class="pick" disabled={solving !== null || !live.app.solver?.available} onclick={() => void solveGroup(group)}>
                  <span class="text">
                    <span class="name">{group.target ?? p.untitled}</span>
                    <span class="muted">{p.frameGroup(group.filter, group.frames, formatPlain(group.exposure / 60, locale))}</span>
                  </span>
                  <Icon name="chevronRight" />
                </button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted">{p.noLights}</p>
        {/if}
        {#if solving}<p class="muted" role="status">{p.solving(solving.name)}</p>{/if}
        {#if !live.app.solver?.available}<p class="muted">{t.center.noSolver}</p>{/if}
      {/if}
    </section>
  {/if}
</div>

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
  h1 {
    margin: 0;
    font-size: 28px;
    line-height: 34px;
  }
  p {
    margin: 0;
  }
  .credit,
  .label {
    font-size: 12px;
    line-height: 16px;
  }
  .search,
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .form > :global(button) {
    align-self: flex-start;
  }
  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .suggestion {
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--line);
    background: var(--surface);
  }
  .results li + li {
    border-top: 1px solid var(--line);
  }
  .results a,
  .pick {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    min-height: 60px;
    padding: var(--space-2) var(--space-4);
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
  }
  .pick:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    font-weight: 500;
  }
  .text .muted {
    font-size: 13px;
    line-height: 18px;
  }
  .up {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    text-align: right;
    font-size: 13px;
    line-height: 18px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  select {
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .error {
    color: var(--error);
  }
</style>
