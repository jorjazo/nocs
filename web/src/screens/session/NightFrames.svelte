<script lang="ts">
  // The frames saved on a night (ADR 0013): what each target and filter got,
  // every frame with its stars and HFR, and downloads. The night's zip says its
  // size first: a night of 52 MB frames is several GB over the rig's Wi-Fi.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import { getFrames, getNights } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatBytes, formatDecimal, formatDuration, formatSeconds } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { FrameRecord, NightGroup, NightInfo } from "../../lib/types";

  const PAGE = 50;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  let nights = $state<NightInfo[] | null>(null);
  let error = $state("");
  let chosen = $state<number | null>(null);
  const night = $derived(nights?.find((n) => n.id === chosen) ?? nights?.[0] ?? null);
  // One group's frames only, or all of the night's.
  let group = $state<NightGroup | null>(null);
  let frames = $state<FrameRecord[]>([]);
  let more = $state(false);
  let loadingMore = $state(false);

  // A frame saved on the main camera, and its preview, which comes with its
  // stars and HFR: list again.
  const latest = $derived.by(() => {
    const camera = live.app.cameras?.main_camera;
    const id = camera?.last_frame?.id;
    return id == null ? null : `${id}:${camera?.preview?.url}`;
  });

  $effect(() => {
    void latest;
    const timer = setTimeout(() => void loadNights(), nights === null ? 0 : 1000);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    const id = night?.id;
    const only = group;
    void latest;
    if (id === undefined) return;
    void loadFrames(id, only);
  });

  async function loadNights(): Promise<void> {
    try {
      nights = await getNights();
      error = "";
    } catch (e) {
      error = errorText(e, t);
    }
  }

  function query(id: number, only: NightGroup | null) {
    return {
      night: id,
      type: only?.frame_type,
      target: only?.target ?? undefined,
      filter: only?.filter ?? undefined,
      limit: PAGE,
    };
  }

  let asked = 0;
  async function loadFrames(id: number, only: NightGroup | null): Promise<void> {
    const ticket = ++asked;
    try {
      const page = await getFrames(query(id, only));
      if (ticket !== asked) return;
      frames = page;
      more = page.length === PAGE;
    } catch (e) {
      if (ticket === asked) error = errorText(e, t);
    }
  }

  async function loadMore(): Promise<void> {
    const last = frames.at(-1);
    if (!night || !last) return;
    loadingMore = true;
    try {
      const page = await getFrames({ ...query(night.id, group), before: last.id });
      frames = [...frames, ...page];
      more = page.length === PAGE;
    } catch (e) {
      error = errorText(e, t);
    } finally {
      loadingMore = false;
    }
  }

  function same(a: NightGroup | null, b: NightGroup): boolean {
    return a !== null && a.frame_type === b.frame_type && a.target === b.target && a.filter === b.filter;
  }

  // A group's zip: the night's, narrowed to that type, target and filter.
  function groupZip(base: string, g: NightGroup): string {
    const params = new URLSearchParams({ type: g.frame_type });
    if (g.target) params.set("target", g.target);
    if (g.filter) params.set("filter", g.filter);
    return `${base}?${params}`;
  }

  function groupName(g: NightGroup): string {
    return [t.live.frameTypes[g.frame_type], g.target, g.filter].filter(Boolean).join(" · ");
  }

  // The night's date as people read it; noon keeps it on the same day everywhere.
  function nightDate(date: string): string {
    return new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(
      new Date(`${date}T12:00:00`),
    );
  }

  function clock(iso: string): string {
    return new Intl.DateTimeFormat(locale, { timeStyle: "medium" }).format(new Date(iso));
  }

  const exposure = $derived(night ? night.groups.reduce((sum, g) => sum + g.exposure, 0) : 0);
  const missing = $derived(frames.find((frame) => !frame.available) ?? null);
</script>

{#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

{#if nights === null}
  {#if !error}<p class="muted" role="status">{t.boot.loading}</p>{/if}
{:else if !night}
  <EmptyState icon="save" title={t.nights.empty} body={t.nights.emptyBody}>
    {#snippet action()}
      <Button variant="primary" onclick={() => router.go({ screen: "live" })}>{t.nights.openLive}</Button>
    {/snippet}
  </EmptyState>
{:else}
  <section class="night" aria-labelledby="night-title">
    <div class="title">
      <h2 class="heading" id="night-title">{t.nights.title}</h2>
      {#if nights.length > 1}
        <label class="picker">
          <span class="visually-hidden">{t.nights.choose}</span>
          <select
            value={night.id}
            onchange={(event) => {
              chosen = Number(event.currentTarget.value);
              group = null;
            }}>
            {#each nights as n (n.id)}
              <option value={n.id}>{nightDate(n.night)} · {t.nights.count(n.frames)}</option>
            {/each}
          </select>
          <Icon name="chevronDown" size={20} />
        </label>
      {/if}
    </div>
    <p class="summary">
      <span class="date">{nightDate(night.night)}{night.site ? ` · ${night.site}` : ""}</span>
      <span class="muted">
        {t.nights.count(night.frames)} · {formatDuration(exposure)} · {formatBytes(night.size, locale)}
      </span>
    </p>

    <!-- A download, so a link; styled as the screen's primary action. -->
    <a class="download primary" href={night.zip_url} download>
      <Icon name="download" />
      {t.nights.downloadNight(formatBytes(night.size, locale))}
    </a>
    <p class="caption muted">{t.nights.zipHint}</p>

    <ul class="groups" aria-label={t.nights.groups}>
      {#each night.groups as g (`${g.frame_type}/${g.target}/${g.filter}`)}
        <li class:chosen={same(group, g)}>
          <button
            type="button"
            class="group"
            aria-pressed={same(group, g)}
            onclick={() => (group = same(group, g) ? null : g)}>
            <span class="name">{groupName(g)}</span>
            <span class="caption muted">
              {t.nights.count(g.frames)} · {formatDuration(g.exposure)} · {formatBytes(g.size, locale)}
            </span>
          </button>
          <a class="icon-link" href={groupZip(night.zip_url, g)} download aria-label={t.nights.downloadGroup(groupName(g), formatBytes(g.size, locale))}>
            <Icon name="download" />
          </a>
        </li>
      {/each}
    </ul>
  </section>

  <section class="frames" aria-labelledby="frames-title">
    <div class="title">
      <h2 class="heading" id="frames-title">{group ? groupName(group) : t.nights.frames}</h2>
      {#if group}<Button variant="text" onclick={() => (group = null)}>{t.nights.all}</Button>{/if}
    </div>
    {#if missing}<Banner icon="alert">{t.nights.missing(missing.volume)}</Banner>{/if}
    <ul class="list">
      {#each frames as frame (frame.id)}
        <li class:unavailable={!frame.available}>
          <div class="frame">
            <span class="mono">{clock(frame.started)}</span>
            <span class="caption muted">
              {[t.live.frameTypes[frame.frame_type], frame.filter, formatSeconds(frame.exposure, locale)].filter(Boolean).join(" · ")}
            </span>
          </div>
          <div class="metrics mono">
            <span>{frame.stars === null ? "—" : t.live.stars(frame.stars)}</span>
            <span class="muted">{frame.hfr === null ? "HFR —" : `HFR ${formatDecimal(frame.hfr, locale, 2)}`}</span>
            {#if frame.guiding?.rms_total != null}
              <span class="muted" class:warning={frame.guiding.lost > 0}>
                {t.nights.guided(formatDecimal(frame.guiding.rms_total, locale, 2), frame.guiding.lost)}
              </span>
            {/if}
          </div>
          {#if frame.available}
            <a class="icon-link" href={frame.url} download aria-label={t.nights.downloadFrame(formatBytes(frame.size, locale))}>
              <Icon name="download" />
            </a>
          {:else}
            <span class="icon-link" aria-hidden="true"></span>
          {/if}
        </li>
      {/each}
    </ul>
    {#if more}
      <Button busy={loadingMore} onclick={() => void loadMore()}>{t.nights.more}</Button>
    {/if}
  </section>
{/if}

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .night {
    margin-bottom: var(--space-8);
  }
  .title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .summary {
    display: flex;
    flex-direction: column;
    margin: 0;
  }
  .date {
    font-size: 17px;
    font-weight: 600;
  }
  .picker {
    position: relative;
    display: inline-flex;
    align-items: center;
  }
  .picker select {
    appearance: none;
    min-height: 48px;
    max-width: 70vw;
    padding: 0 44px 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    font-weight: 500;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .picker :global(.icon) {
    position: absolute;
    right: 14px;
    pointer-events: none;
  }
  .download {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    min-height: var(--primary-height);
    padding: 0 var(--space-4);
    border-radius: var(--radius-button);
    font-size: 17px;
    font-weight: 600;
    text-decoration: none;
  }
  @media (min-width: 768px) {
    .download {
      align-self: flex-start;
    }
  }
  .download.primary {
    background: var(--accent);
    color: var(--on-accent);
  }
  ul {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
  }
  li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-2);
    padding-left: var(--space-3);
  }
  li + li {
    border-top: 1px solid var(--line);
  }
  .groups li.chosen {
    background: color-mix(in srgb, var(--accent) var(--tint), transparent);
  }
  .group {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    min-width: 0;
    min-height: 56px;
    padding: var(--space-2) 0;
    border: 0;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .list li {
    grid-template-columns: minmax(0, 1fr) auto auto;
    min-height: 56px;
  }
  .frame,
  .metrics {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .metrics {
    align-items: flex-end;
    font-size: 14px;
  }
  .metrics .warning {
    color: var(--warning);
  }
  .unavailable {
    opacity: 0.55;
  }
  .icon-link {
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    color: var(--accent);
  }
</style>
