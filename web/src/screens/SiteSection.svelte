<script lang="ts">
  // Rig's site (ADR 0038): the box's saved sites and the active one, whatever
  // the profile; the owner chooses which is active, and a GPS with a fix offers
  // the saved site it is at, or to save its position as a new one.
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
  import DeviceRow from "../components/DeviceRow.svelte";
  import { activateSite, useGpsSite } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { formatDecimal, formatPlain } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { href, router } from "../lib/router.svelte";
  import type { Site } from "../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const sites = $derived(live.app.sites ?? null);
  const active = $derived(sites?.active ?? null);
  const saved = $derived(
    Object.entries(sites?.saved ?? {}).sort(([, a], [, b]) => (a.name || "").localeCompare(b.name || "")),
  );

  function coordinates(site: Site): string {
    return t.sites.coordinates(
      `${formatDecimal(site.latitude, locale, 4)}°`,
      `${formatDecimal(site.longitude, locale, 4)}°`,
      `${formatPlain(site.elevation ?? 0, locale)} m`,
    );
  }

  // What a GPS with a 3D fix offers: the saved site it is at, unless that is the
  // active one, or a new site where none is saved.
  const gps = $derived(live.app.gps?.connected && live.app.gps.fix === "3d" ? live.app.gps : null);
  const offer = $derived.by(() => {
    if (!gps || !auth.owner) return null;
    if (gps.site === null) return { text: t.sites.gpsElsewhere, label: t.sites.gpsSave };
    if (gps.site === active) return null;
    const site = sites?.saved[gps.site];
    return { text: t.sites.gpsAt(site?.name || t.sites.unnamed), label: t.sites.gpsUse };
  });

  let busy = $state<string | null>(null);
  let error = $state("");

  async function run(key: string, action: () => Promise<unknown>): Promise<void> {
    busy = key;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

<section aria-labelledby="site-title">
  <div class="line section-title">
    <h2 class="heading" id="site-title">{t.sites.title}</h2>
    {#if auth.owner}<a href={href({ screen: "site", id: null })}>{t.sites.newSite}</a>{/if}
  </div>
  <p class="caption muted">{t.sites.hint}</p>
  {#if saved.length === 0}
    <p class="muted">{t.sites.none}</p>
  {:else}
    <ul class="rows">
      {#each saved as [id, site] (id)}
        <DeviceRow
          icon="home"
          title={site.name || t.sites.unnamed}
          subtitle={coordinates(site)}
          onclick={auth.owner ? () => router.go({ screen: "site", id }) : undefined}>
          {#snippet trailing()}
            {#if id === active}
              <Chip tone="ok">{t.sites.active}</Chip>
            {:else if auth.owner}
              <Button variant="text" busy={busy === id} onclick={() => void run(id, () => activateSite(id))}>{t.sites.use}</Button>
            {/if}
          {/snippet}
        </DeviceRow>
      {/each}
    </ul>
  {/if}
  {#if offer}
    <div class="gps">
      <span class="muted">{offer.text}</span>
      <Button busy={busy === "gps"} onclick={() => void run("gps", () => useGpsSite())}>{offer.label}</Button>
    </div>
  {/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .line a {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  .rows {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .gps {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
</style>
