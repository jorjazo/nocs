<script lang="ts">
  // Plan → Target (stage 3.6): tonight's target, if one is chosen, and the
  // catalog search with how long each result is up in the dark tonight. A result
  // opens the target's page (#/plan/<id>). The sequence builder is the other
  // half of Plan (#/plan/sequence).
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Icon from "../../components/Icon.svelte";
  import PlanSwitch from "./PlanSwitch.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import TextField from "../../components/TextField.svelte";
  import { forgetPlanTarget, getVisibility, searchTargets } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatDuration } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa } from "../../lib/mount.svelte";
  import { href, router } from "../../lib/router.svelte";
  import { plannedName } from "../../lib/catalog.svelte";
  import { objectName, objectSummary } from "../../lib/targets";
  import type { CatalogMatch, TargetVisibility } from "../../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const planned = $derived(live.app.plan?.target ?? null);

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
</script>

<ScreenHeader title={t.tabs.plan}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

<div class="screen">
  <PlanSwitch value="target" />
  {#if planned}
    <section class="card current" aria-labelledby="planned-title">
      <span class="label muted">{t.plan.tonightsTarget}</span>
      <h2 id="planned-title">{plannedName(planned, locale)}</h2>
      <p class="muted mono">{formatRa(planned.ra)} · {formatDec(planned.dec)}</p>
      <div class="buttons">
        {#if planned.id}
          <Button variant="primary" onclick={() => router.go({ screen: "target", id: planned.id ?? "" })}>{t.plan.open}</Button>
        {/if}
        {#if auth.owner}
          <ConfirmButton label={t.plan.forget} confirmLabel={t.plan.forgetConfirm} onconfirm={() => void forgetPlanTarget().catch((e) => (error = errorText(e, t)))} />
        {/if}
      </div>
    </section>
  {/if}

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
  </section>

  <p class="credit muted">{t.plan.credit}</p>
</div>

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-4);
  }
  .current {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h2,
  p {
    margin: 0;
  }
  .label,
  .credit {
    font-size: 12px;
    line-height: 16px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .search {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
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
    border-radius: var(--radius-full);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: var(--surface);
  }
  .results li + li {
    border-top: 1px solid var(--line);
  }
  .results a {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 60px;
    padding: var(--space-2) var(--space-4);
    color: var(--text);
    text-decoration: none;
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
  .error {
    color: var(--error);
  }
</style>
