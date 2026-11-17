<script lang="ts">
  // Go to, at the right of Explore's image (ADR 0054): the slew pad, then a search of
  // what is above the horizon now (catalog objects, the Sun and the Moon) with "Go"
  // and "Go and centre". Going somewhere names the frames saved there after it. For
  // the Sun or the Moon, "Go and centre" runs their finder (ADR 0049); near the Sun,
  // its warning comes first. Refused go tos say why and offer the way on, as the
  // target's page does.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import { ApiError, centerOn, findBody, gotoMount, searchUp, setTarget } from "../../lib/api";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal } from "../../lib/format";
  import { goRefusal } from "../../lib/goto";
  import { guidingActive } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa, mountActivity } from "../../lib/mount.svelte";
  import type { MountState, SkyMatch } from "../../lib/types";
  import FinderCard from "../devices/FinderCard.svelte";
  import MountPad from "../devices/MountPad.svelte";
  import SunWarning from "../devices/SunWarning.svelte";
  import CenteringCard from "./CenteringCard.svelte";
  import ToolCard from "./ToolCard.svelte";

  let {
    mount,
    owner,
    open,
    ontoggle,
  }: {
    mount: MountState;
    owner: boolean;
    open: boolean;
    ontoggle: () => void;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const guiding = $derived(guidingActive(live.app.guiding));
  const mountJob = $derived(holder(live.app.jobs, "mount"));
  const activity = $derived(mountActivity(mount, t));

  const padReason = $derived.by((): string | null => {
    if (!owner) return t.mount.locked;
    if (mount.parked) return t.mount.padParked;
    if (guiding) return t.guiding.padHeld;
    if (mountJob) return t.mount.padBusy;
    return null;
  });
  const goReason = $derived.by((): string | null => {
    if (!owner) return t.plan.ownerOnly;
    if (mount.parked) return t.plan.parked;
    if (mountJob) return mountJob.info.kind === "goto" || mountJob.info.kind === "center" ? t.plan.mountGoing : t.plan.mountBusy;
    return null;
  });
  const centerReason = $derived.by((): string | null => {
    if (goReason) return goReason;
    if (!live.app.cameras?.main_camera) return t.center.noCamera;
    if (holder(live.app.jobs, "main_camera")) return t.center.cameraBusy;
    if (!chosen?.body && !live.app.solver?.available) return t.center.noSolver;
    return null;
  });

  // -- The search ----------------------------------------------------------------------

  let query = $state("");
  let matches = $state<SkyMatch[]>([]);
  let searched = $state("");
  let searchError = $state("");
  let chosen = $state<SkyMatch | null>(null);
  let asked = 0;

  // Asked a moment after typing stops; only the latest answer counts. A new search
  // drops the choice, so Go never goes to something no longer listed.
  $effect(() => {
    const text = query.trim();
    chosen = null;
    if (!text) {
      matches = [];
      searched = "";
      searchError = "";
      return;
    }
    const id = ++asked;
    const timer = setTimeout(() => {
      searchUp(text, 8)
        .then((found) => {
          if (id !== asked) return;
          matches = found;
          searched = text;
          searchError = "";
        })
        .catch((e: unknown) => {
          if (id !== asked) return;
          matches = [];
          searchError = errorText(e, t);
        });
    }, 250);
    return () => clearTimeout(timer);
  });

  function name(match: SkyMatch): string {
    return match.body ? t.finder.bodies[match.body] : (match.object?.label ?? match.matched);
  }
  // What names the lights saved there: the catalog's label, or the body in English,
  // whatever language the device that went there speaks.
  const BODY_NAMES = { sun: "Sun", moon: "Moon" } as const;
  function targetName(match: SkyMatch): string {
    return match.body ? BODY_NAMES[match.body] : (match.object?.label ?? match.matched);
  }
  function detail(match: SkyMatch): string {
    const parts = [t.live.altitude(formatDecimal(match.altitude, locale, 0))];
    if (match.object && match.matched !== match.object.label) parts.unshift(match.matched);
    else if (match.object?.names[0] && match.object.names[0] !== match.object.label) parts.unshift(match.object.names[0]);
    return parts.join(" · ");
  }

  // -- Going ---------------------------------------------------------------------------

  type Go = "goto" | "center";
  let busy = $state<Go | null>(null);
  let error = $state("");
  let belowHorizon = $state<{ kind: Go; stopGuiding: boolean } | null>(null);
  let guidingRefused = $state<Go | null>(null);
  let nearSun = $state<(() => void) | null>(null);

  async function go(kind: Go, force = false, stopGuiding = false, acknowledged = false): Promise<void> {
    const target = chosen;
    if (!target) return;
    if (target.body === "sun" && !mount.sun_acknowledged && !acknowledged) {
      nearSun = () => void go(kind, force, stopGuiding, true);
      return;
    }
    busy = kind;
    error = "";
    belowHorizon = null;
    guidingRefused = null;
    try {
      if (target.body && kind === "center") {
        await findBody({ body: target.body, radius: 5, stop_guiding: stopGuiding || target.body === "sun" });
      } else if (kind === "center") {
        await centerOn({ ra: target.ra, dec: target.dec, force, stop_guiding: stopGuiding });
      } else {
        // The Sun and the Moon move: where they are now, not when they were found.
        const now = target.body
          ? ((await searchUp(target.body, 5)).find((m) => m.body === target.body) ?? target)
          : target;
        await gotoMount({ frame: now.frame, ra: now.ra, dec: now.dec, force, stop_guiding: stopGuiding });
      }
      // The frames saved here are named after it (ADR 0054).
      await setTarget(targetName(target));
    } catch (e) {
      const why = e instanceof ApiError ? goRefusal(e.status, e.message) : null;
      if (why === "horizon") belowHorizon = { kind, stopGuiding };
      else if (why === "guiding") guidingRefused = kind;
      else if (why === "sun") nearSun = () => void go(kind, force, stopGuiding, true);
      else error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  const finder = $derived(live.app.finder?.state === "running" ? live.app.finder : null);
  const centering = $derived(live.app.centering ?? null);
</script>

<ToolCard
  icon="mount"
  title={t.mount.goTo}
  side="right"
  {open}
  {ontoggle}
  tone={activity.moving ? "accent" : null}
  toneText={activity.text}>
  {#snippet status()}<span class="caption muted">{activity.text}</span>{/snippet}
  <p class="position mono">{formatRa(mount.ra_j2000)} {formatDec(mount.dec_j2000)}</p>
  <MountPad {mount} compact narrow disabled={padReason !== null} reason={padReason} />

  <label class="search">
    <span class="caption muted">{t.live.searchUp}</span>
    <input
      type="search"
      bind:value={query}
      placeholder={t.live.searchUpHint}
      autocomplete="off"
      spellcheck="false" />
  </label>
  {#if searchError}
    <p class="caption warning">{searchError}</p>
  {:else if searched && matches.length === 0}
    <p class="caption muted">{t.live.searchUpNone}</p>
  {/if}
  {#if matches.length > 0}
    <ul class="matches" role="listbox" aria-label={t.live.searchUp}>
      {#each matches as match (`${match.body ?? match.object?.id}`)}
        {@const selected = chosen !== null && name(chosen) === name(match)}
        <li>
          <button type="button" role="option" aria-selected={selected} class:selected onclick={() => (chosen = match)}>
            <span class="name">{name(match)}</span>
            <span class="caption muted">{detail(match)}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if chosen}
    <div class="buttons">
      <Button disabled={goReason !== null || busy !== null} busy={busy === "goto"} onclick={() => void go("goto")}>
        {t.live.go}
      </Button>
      <Button
        variant="primary"
        disabled={centerReason !== null || busy !== null}
        busy={busy === "center"}
        onclick={() => void go("center")}>
        {t.center.goCenter}
      </Button>
    </div>
    {#if centerReason ?? goReason}<p class="caption muted">{centerReason ?? goReason}</p>{/if}
  {/if}

  {#if belowHorizon}
    {@const refused = belowHorizon}
    <Banner icon="alert" tone="warning">
      {t.mount.belowHorizon}
      {#snippet action()}
        <ConfirmButton label={t.mount.goAnyway} confirmLabel={t.mount.goAnywayConfirm} onconfirm={() => void go(refused.kind, true, refused.stopGuiding)} />
      {/snippet}
    </Banner>
  {/if}
  {#if guidingRefused}
    {@const kind = guidingRefused}
    <Banner icon="alert" tone="warning">
      {t.live.guidingHolds}
      {#snippet action()}
        <Button variant="text" onclick={() => void go(kind, false, true)}>{t.plan.goStopGuiding}</Button>
      {/snippet}
    </Banner>
  {/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {#if finder}<FinderCard {finder} />{/if}
  {#if centering}<CenteringCard {centering} />{/if}
</ToolCard>

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
  .position {
    margin: 0;
    font-size: 15px;
  }
  .search {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  input {
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-button);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .matches {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 220px;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    list-style: none;
  }
  .matches button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    min-height: var(--touch);
    padding: var(--space-1) var(--space-2);
    border: 1px solid transparent;
    border-radius: var(--radius-tile);
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .matches button.selected {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) var(--tint), var(--surface));
  }
  .name {
    font-weight: 600;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .warning {
    color: var(--warning);
  }
</style>
