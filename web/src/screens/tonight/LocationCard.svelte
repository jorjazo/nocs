<script lang="ts">
  // Tonight's "Location and time" card, for the owner only (observers do not see
  // where the box is, ADR 0047): the active site with its time zone (ADR 0052) and
  // the box's time and what keeps it; the mount's site and clock; the GPS's fix.
  // Warns when the mount is at another site or lacks NOCS's time, and when the box's
  // clock is off, with a link to the site in Rig. Closed: the site, the time, and whether all
  // matches.
  import Section from "../../components/Section.svelte";
  import { formatClock, formatDecimal, formatDuration, formatTime, timeZone } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href } from "../../lib/router.svelte";

  let { now, open, ontoggle }: { now: number; open: boolean; ontoggle: (open: boolean) => void } = $props();

  const t = $derived(i18n.t);
  const l = $derived(t.tonight.location);
  const locale = $derived(i18n.locale);
  const sites = $derived(live.app.sites ?? null);
  const site = $derived(sites?.active ? (sites.saved[sites.active] ?? null) : null);
  const clock = $derived(live.app.clock ?? null);
  const mount = $derived(live.app.mount ?? null);
  const gps = $derived(live.app.gps?.connected ? live.app.gps : null);

  // While open, the clocks show their seconds, and tick.
  let tick = $state(Date.now());
  $effect(() => {
    if (!open) return;
    tick = Date.now();
    const timer = setInterval(() => (tick = Date.now()), 1000);
    return () => clearInterval(timer);
  });
  const clientNow = $derived(open ? tick : now);
  // The box's own clock, from what this client last reported against it; the mount
  // gets the time NOCS trusts (this client's when the box's is off, ADR 0029).
  const boxNow = $derived(clientNow - (clock?.offset ?? 0) * 1000);
  // The mount's clock as its driver last sent it, which may be long ago: what tells
  // is whether NOCS gave it the time since it became ready (go to waits for it).
  const mountClockOff = $derived(!!mount && !mount.time_sent);
  const siteOff = $derived(mount?.site_check === "different");
  const clockOff = $derived(!!clock?.corrected);
  const trouble = $derived(siteOff || mountClockOff || clockOff || !site);

  const degrees = (value: number) => `${formatDecimal(value, locale, 4)}°`;
  const time = (ms: number) => formatClock(new Date(ms).toISOString(), locale);

  const summary = $derived(
    [site ? site.name || t.sites.unnamed : l.noSite, formatTime(new Date(boxNow).toISOString(), locale), trouble ? null : l.allMatch]
      .filter((p) => p !== null)
      .join(" · "),
  );
  const status = $derived(trouble && site ? { tone: "warning" as const, text: l.check } : null);
</script>

<Section scope="tonight" id="location" title={l.title} {summary} {status} {open} {ontoggle}>
  <div class="group">
    <h3 class="label">{l.site}</h3>
    {#if site}
      <div class="row">
        <span>{site.name || t.sites.unnamed}</span>
        <span class="muted">{l.position(degrees(site.latitude), degrees(site.longitude))}</span>
      </div>
      <span class="muted small">{l.zone(timeZone() ?? site.zone)}</span>
    {:else}
      <span>{l.noSite}</span>
    {/if}
  </div>

  <div class="group">
    <h3 class="label">{l.boxTime}</h3>
    <div class="row">
      <span class="mono">{time(boxNow)}</span>
      {#if clock?.source}<span class="muted">{t.system.timeSource[clock.source]}</span>{/if}
    </div>
    {#if clockOff && clock?.offset !== null && clock?.offset !== undefined}
      <span class="warning small">
        {clock.offset > 0 ? t.clock.behind(formatDuration(clock.offset)) : t.clock.ahead(formatDuration(clock.offset))}
      </span>
    {/if}
  </div>

  {#if mount}
    <div class="group">
      <h3 class="label">{l.mount}</h3>
      <div class="row">
        <span class:warning={siteOff}>{l.siteCheck[mount.site_check]}</span>
        {#if mount.site}
          <span class="muted">{l.position(degrees(mount.site.latitude), degrees(mount.site.longitude))}</span>
        {/if}
      </div>
      <div class="row">
        <span class:warning={mountClockOff}>{mountClockOff ? l.timeNotSent : l.timeSent}</span>
        {#if mount.time}<span class="muted small">{l.mountTime(formatClock(mount.time, locale))}</span>{/if}
      </div>
    </div>
  {/if}

  {#if gps}
    <div class="group">
      <h3 class="label">{l.gps}</h3>
      <div class="row">
        <span>{gps.fix === "none" ? t.system.gpsNoFix : t.system.gpsFix(gps.fix.toUpperCase())}</span>
        {#if gps.latitude !== null && gps.longitude !== null}
          <span class="muted">{l.position(degrees(gps.latitude), degrees(gps.longitude))}</span>
        {/if}
      </div>
      {#if gps.time}<span class="muted small">{l.gpsTime(formatClock(gps.time, locale))}</span>{/if}
    </div>
  {/if}

  {#if trouble}
    <a class="fix" href={href({ screen: "rig", section: "site" })}>{l.fix}</a>
  {/if}
</Section>

<style>
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h3 {
    margin: 0;
    color: var(--muted);
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .small {
    font-size: 13px;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 14px;
  }
  .warning {
    color: var(--warning);
  }
  .fix {
    align-self: flex-start;
    min-height: var(--touch);
    display: inline-flex;
    align-items: center;
    font-weight: 600;
  }
</style>
