<script lang="ts">
  // Tonight's "Pointing" card: where the mount points (altitude and azimuth, RA and
  // Dec), what is there (tonight's target when it is in the frame, else the Sun or
  // the Moon, else the nearest catalog object), its altitude through the night, and
  // the guiding error. Closed: the object, its altitude and the RMS.
  import AltitudeChart from "../../components/AltitudeChart.svelte";
  import Section from "../../components/Section.svelte";
  import { getSkyPointing, getVisibility } from "../../lib/api";
  import { plannedName } from "../../lib/catalog.svelte";
  import { formatDecimal } from "../../lib/format";
  import { guidingActive } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa } from "../../lib/mount.svelte";
  import { objectName } from "../../lib/targets";
  import { frameRadius, movedFrom, pointedAt, type Sky } from "../../lib/tonightcards";
  import type { Almanac, SkyPointing, TargetVisibility } from "../../lib/types";

  let {
    almanac,
    now,
    open,
    ontoggle,
  }: { almanac: Almanac | null; now: number; open: boolean; ontoggle: (open: boolean) => void } = $props();

  // The Sun and the Moon move: what is around the mount is asked again now and then.
  const REASK = 5 * 60_000;
  const MIN_ALTITUDE = 30;

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const mount = $derived(live.app.mount ?? null);
  const planned = $derived(live.app.plan?.target ?? null);
  const radius = $derived(frameRadius(live.app.cameras?.main_camera?.field));
  const at = $derived<Sky | null>(mount ? { ra: mount.ra_j2000, dec: mount.dec_j2000 } : null);

  let around: SkyPointing | null = $state(null);
  let asked: Sky | null = null;
  let askedAt = 0;
  $effect(() => {
    if (!at || mount?.slewing) return;
    const moved = movedFrom(asked, at, radius);
    if (!moved && now - askedAt < REASK) return;
    const here = at;
    // What was around the last field is not around this one.
    if (moved) around = null;
    asked = here;
    askedAt = now;
    getSkyPointing(here.ra, here.dec, radius)
      .then((found) => {
        if (asked === here) around = found;
      })
      .catch(() => {
        // Asked again in a minute; what is shown stays while the mount stays.
        if (asked === here) askedAt = Date.now() - REASK + 60_000;
      });
  });

  const pointed = $derived(at ? pointedAt(at, radius, planned, around) : null);
  const name = $derived.by(() => {
    switch (pointed?.kind) {
      case "planned":
        return plannedName(pointed.target, locale);
      case "body":
        return pointed.body === "sun" ? t.tonight.pointing.sun : t.tonight.pointing.moon;
      case "catalog":
        return objectName(pointed.object, locale);
      default:
        return null;
    }
  });

  // The altitude through the night: the Sun's and the Moon's come with the almanac;
  // anything else is asked for once per object (or per tenth of a degree of sky).
  const visibilityKey = $derived.by(() => {
    if (!pointed || !at || pointed.kind === "body") return null;
    if (pointed.kind === "planned") return `${pointed.target.ra},${pointed.target.dec}`;
    if (pointed.kind === "catalog") return pointed.object.id;
    return `${at.ra.toFixed(2)},${at.dec.toFixed(1)}`;
  });
  let seen: TargetVisibility | null = $state(null);
  let seenFor = "";
  $effect(() => {
    const key = visibilityKey && almanac ? `${visibilityKey}|${almanac.night}` : "";
    if (key === seenFor) return;
    seenFor = key;
    seen = null;
    if (!key || !visibilityKey) return;
    getVisibility([visibilityKey])
      .then((v) => {
        if (seenFor === key) seen = v.targets[0] ?? null;
      })
      .catch(() => {
        if (seenFor === key) seenFor = ""; // asked again when the card next updates
      });
  });
  const curve = $derived.by(() => {
    if (!almanac) return null;
    if (pointed?.kind === "body") {
      const altitude = pointed.body === "moon" ? almanac.moon.altitude : almanac.sun_altitude;
      return { altitude, horizon: almanac.times.map(() => 0) };
    }
    return seen ? { altitude: seen.altitude, horizon: seen.horizon } : null;
  });

  const guiding = $derived(live.app.guiding ?? null);
  const stats = $derived(guidingActive(guiding) ? (guiding?.stats ?? null) : null);
  const arcsec = (value: number | null | undefined) => (value === null || value === undefined ? "—" : formatDecimal(value, locale, 2));

  const summary = $derived.by(() => {
    if (!mount) return t.tonight.pointing.noMount;
    if (mount.parked) return t.tonight.pointing.parked;
    const parts = [
      mount.slewing ? t.tonight.pointing.slewing : (name ?? `${formatRa(mount.ra_j2000)} ${formatDec(mount.dec_j2000)}`),
      mount.alt === null ? null : `${formatDecimal(mount.alt, locale, 0)}°`,
      stats?.rms_total != null ? t.tonight.pointing.rms(formatDecimal(stats.rms_total, locale, 1)) : null,
    ];
    return parts.filter((part) => part !== null).join(" · ");
  });
</script>

<Section scope="tonight" id="pointing" title={t.tonight.pointing.title} {summary} {open} {ontoggle}>
  {#if !mount}
    <p class="muted">{t.tonight.pointing.noMountBody}</p>
  {:else}
    <div class="facts">
      <div>
        <span class="label muted">{t.tonight.pointing.object}</span>
        {#if name}<span class="readout">{name}</span>{:else}<span>{t.tonight.pointing.none}</span>{/if}
        <span class="muted">
          {#if mount.parked}{t.tonight.pointing.parked}
          {:else if mount.slewing}{t.tonight.pointing.slewing}
          {:else if pointed?.kind === "planned"}{t.tonight.pointing.planned}{/if}
        </span>
      </div>
      <div>
        <span class="label muted">{t.tonight.pointing.guiding}</span>
        {#if stats}
          <span class="readout">{t.tonight.pointing.rms(arcsec(stats.rms_total))}</span>
          <span class="muted">{t.tonight.pointing.rmsAxes(arcsec(stats.rms_ra), arcsec(stats.rms_dec))}</span>
        {:else}
          <span class="readout">—</span>
          <span class="muted">{t.tonight.pointing.notGuiding}</span>
        {/if}
      </div>
      <div>
        <span class="label muted">{t.tonight.pointing.altAz}</span>
        <span class="mono">
          {mount.alt === null ? "—" : `${formatDecimal(mount.alt, locale, 1)}°`} ·
          {mount.az === null ? "—" : `${formatDecimal(mount.az, locale, 1)}°`}
        </span>
      </div>
      <div>
        <span class="label muted">{t.tonight.pointing.raDec}</span>
        <span class="mono">{formatRa(mount.ra_j2000)} · {formatDec(mount.dec_j2000)}</span>
      </div>
    </div>
    {#if almanac && curve}
      <AltitudeChart
        times={almanac.times}
        sunAltitude={almanac.sun_altitude}
        altitude={curve.altitude}
        horizon={curve.horizon}
        moon={pointed?.kind === "body" ? null : almanac.moon.altitude}
        minAltitude={MIN_ALTITUDE}
        {now} />
      <p class="caption muted">{t.tonight.pointing.legend}</p>
    {/if}
  {/if}
</Section>

<style>
  .facts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
  }
  .facts > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .label,
  .caption {
    font-size: 12px;
    line-height: 16px;
  }
  .readout {
    font-size: 20px;
    line-height: 26px;
    overflow-wrap: anywhere;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 14px;
  }
  p {
    margin: 0;
  }
</style>
