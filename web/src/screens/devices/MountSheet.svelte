<script lang="ts">
  // The mount: where it points, the slew pad, go to (J2000 or the zenith) and go
  // and centre, tracking, park and home, the site and time it was given, and the limits it
  // keeps. Opened from Rig and from Live view.
  import Banner from "../../components/Banner.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import TextField from "../../components/TextField.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import {
    abortMount,
    ApiError,
    centerOn,
    gotoMount,
    homeMount,
    parkMount,
    sendMountSite,
    sendMountTime,
    setTracking,
    stopGuiding,
    unparkMount,
  } from "../../lib/api";
  import { guidingActive } from "../../lib/guiding.svelte";
  import { auth } from "../../lib/auth.svelte";
  import { holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDateTime, formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { formatDec, formatRa, mountActivity, parseDec, parseRa } from "../../lib/mount.svelte";
  import { router } from "../../lib/router.svelte";
  import CenteringCard from "../live/CenteringCard.svelte";
  import MountPad from "./MountPad.svelte";

  let { onclose }: { onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const mount = $derived(live.app.mount ?? null);
  const owner = $derived(auth.owner);
  const job = $derived(holder(live.app.jobs, "mount"));
  const activity = $derived(mount ? mountActivity(mount, t) : null);

  let busy = $state<string | null>(null);
  let error = $state("");
  // A go to (or go and centre) refused below the horizon, ready to be forced.
  let refused = $state<{ ra: number; dec: number; center: boolean } | null>(null);

  async function run(kind: string, action: () => Promise<unknown>): Promise<void> {
    busy = kind;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  // The mount went away (disconnected): nothing left to control.
  $effect(() => {
    if (!mount) onclose();
  });

  // -- Go to ------------------------------------------------------------------------

  let raText = $state("");
  let decText = $state("");
  let tried = $state(false);
  const ra = $derived(parseRa(raText));
  const dec = $derived(parseDec(decText));

  async function goTo(force = false, center = false): Promise<void> {
    tried = true;
    if (ra === null || dec === null) return;
    const target = { ra, dec, center };
    refused = null;
    busy = center ? "center" : "goto";
    error = "";
    try {
      if (center) await centerOn({ ra: target.ra, dec: target.dec, force });
      else await gotoMount({ frame: "j2000", ra: target.ra, dec: target.dec, force });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message.includes("below the horizon")) refused = target;
      else error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  // -- Go and centre (stage 3.3) ----------------------------------------------------

  const centering = $derived(live.app.centering ?? null);
  const centerReason = $derived.by((): string | null => {
    if (!live.app.solver?.available) return t.center.noSolver;
    if (!live.app.cameras?.main_camera) return t.center.noCamera;
    if (holder(live.app.jobs, "main_camera")) return t.center.cameraBusy;
    return null;
  });
  // What the centring that holds the mount is doing, in this language.
  const progress = $derived.by((): string | null => {
    if (!job) return null;
    if (centering && centering.job === job.id && centering.state === "running") {
      const attempt = Math.min(centering.attempts.length + 1, centering.max_attempts);
      const phase = t.center.phases[centering.phase ?? "slewing"];
      return `${t.center.title} · ${t.center.phase(phase, attempt, centering.max_attempts)}`;
    }
    return job.info.message;
  });

  // -- Readouts -----------------------------------------------------------------------

  const degrees = (value: number, digits = 1) => `${formatDecimal(value, locale, digits)}°`;
  const siteText = $derived(
    mount?.site ? `${degrees(mount.site.latitude, 2)}, ${degrees(mount.site.longitude, 2)}` : "—",
  );
  const siteCheck = $derived.by(() => {
    switch (mount?.site_check) {
      case "same":
        return t.mount.siteSame;
      case "different":
        return t.mount.siteDifferent;
      case "no_profile_site":
        return t.mount.noProfileSite;
      default:
        return t.mount.siteUnknown;
    }
  });
  const modes = $derived(
    (mount?.track_modes ?? []).map((value) => ({ value, label: t.mount.modes[value] ?? value })),
  );
  // PHD2 calibrates or guides: NOCS holds the mount until guiding stops (ADR 0023).
  const guiding = $derived(guidingActive(live.app.guiding));
  const padReason = $derived.by((): string | null => {
    if (!owner) return t.mount.locked;
    if (mount?.parked) return t.mount.padParked;
    if (guiding) return t.guiding.padHeld;
    if (job) return t.mount.padBusy;
    return null;
  });
</script>

<Sheet title={mount?.device ?? t.mount.title} {onclose}>
  {#if mount && activity}
    <div class="position">
      <div class="coordinates">
        <span class="label muted">{t.mount.position} · J2000</span>
        <span class="readout mono">{formatRa(mount.ra_j2000)}</span>
        <span class="readout mono">{formatDec(mount.dec_j2000)}</span>
        <span class="caption muted mono">{t.mount.jnow(formatRa(mount.ra), formatDec(mount.dec))}</span>
        <!-- Lines that come and go would move the pad under a finger: they stay, blank. -->
        <span class="caption muted mono">
          {mount.alt !== null && mount.az !== null ? t.mount.altAz(degrees(mount.alt), degrees(mount.az)) : "\u00a0"}
        </span>
        <span class="caption muted">{mount.pier_side !== "unknown" ? t.mount.pier(mount.pier_side) : "\u00a0"}</span>
      </div>
      <Chip tone={activity.moving ? "accent" : mount.tracking ? "ok" : "neutral"}>{activity.text}</Chip>
    </div>

    {#if guiding}
      <Banner icon="guide" tone="warning">
        {t.guiding.mountHeld}
        {#snippet action()}
          {#if owner}
            <Button variant="text" disabled={busy !== null} onclick={() => void run("guiding", stopGuiding)}>
              {t.guiding.stop}
            </Button>
          {/if}
        {/snippet}
      </Banner>
    {/if}

    <section aria-label={t.mount.pad}>
      <MountPad {mount} disabled={padReason !== null} reason={padReason} />
    </section>

    <!-- Below the pad and always there: nothing above the arrows may appear or move
         while they are held. -->
    <div class="running">
      <Button
        variant="danger"
        wide
        disabled={!owner || !(job || activity.moving)}
        busy={busy === "abort"}
        onclick={() => void run("abort", abortMount)}>
        {t.mount.stop}
      </Button>
      {#if progress}<p class="caption muted" role="status">{progress}</p>{/if}
    </div>

    <SequenceHold resources={["mount"]} />
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

    <section class="group" aria-labelledby="goto-title">
      <h3 class="label muted" id="goto-title">{t.mount.goTo}</h3>
      {#if !mount.site_sent}
        <p class="caption warning">{t.mount.waitingSite}</p>
      {:else if !mount.time_sent}
        <p class="caption warning">{t.mount.waitingTime}</p>
      {/if}
      <div class="fields">
        <TextField
          label={t.mount.ra}
          placeholder="00 42 44"
          bind:value={raText}
          error={tried && ra === null ? t.mount.badRa : undefined} />
        <TextField
          label={t.mount.dec}
          placeholder="+41 16 09"
          bind:value={decText}
          error={tried && dec === null ? t.mount.badDec : undefined} />
      </div>
      <p class="caption muted">{t.mount.goToHint}</p>
      {#if refused}
        <Banner icon="alert" tone="warning">
          {t.mount.belowHorizon}
          {#snippet action()}
            <ConfirmButton
              label={t.mount.goAnyway}
              confirmLabel={t.mount.goAnywayConfirm}
              onconfirm={() => void goTo(true, refused?.center)} />
          {/snippet}
        </Banner>
      {/if}
      <div class="buttons">
        <Button variant="primary" disabled={!owner || !!job || mount.parked} busy={busy === "goto"} onclick={() => void goTo()}>
          {t.mount.go}
        </Button>
        <Button
          disabled={!owner || !!job || mount.parked || centerReason !== null}
          busy={busy === "center"}
          onclick={() => void goTo(false, true)}>
          {t.center.goCenter}
        </Button>
        <Button
          disabled={!owner || !!job || mount.parked}
          busy={busy === "zenith"}
          onclick={() => void run("zenith", () => gotoMount({ frame: "altaz", alt: 90, az: 0 }))}>
          {t.mount.zenith}
        </Button>
      </div>
      <p class="caption muted">{centerReason ?? t.center.hint}</p>
      <p class="caption muted">{t.mount.zenithHint}</p>
      {#if centering}<CenteringCard {centering} />{/if}
    </section>

    <section class="group" aria-label={t.mount.tracking}>
      <Toggle
        label={t.mount.tracking}
        checked={mount.tracking}
        disabled={!owner || !!job || mount.parked || busy === "tracking"}
        onchange={(on) => void run("tracking", () => setTracking({ on }))} />
      {#if modes.length > 1 && mount.track_mode}
        <SegmentedControl
          label={t.mount.trackingMode}
          options={modes}
          value={mount.track_mode}
          disabled={!owner || !!job || busy === "tracking"}
          onchange={(mode) => void run("tracking", () => setTracking({ mode }))} />
      {/if}
    </section>

    {#if live.app.cameras?.main_camera}
      <Button wide onclick={() => router.go({ screen: "polar" })}>{t.polar.open}</Button>
    {/if}

    {#if owner}
      <div class="buttons">
        {#if mount.parked}
          <Button busy={busy === "unpark"} disabled={!!job} onclick={() => void run("unpark", unparkMount)}>{t.mount.unpark}</Button>
        {:else if mount.can_park}
          <ConfirmButton
            label={t.mount.park}
            confirmLabel={t.mount.parkConfirm}
            busy={busy === "park"}
            onconfirm={() => void run("park", parkMount)} />
        {/if}
        {#if mount.can_home && !mount.parked}
          <ConfirmButton
            label={t.mount.home}
            confirmLabel={t.mount.homeConfirm}
            busy={busy === "home"}
            onconfirm={() => void run("home", homeMount)} />
        {/if}
      </div>
    {/if}

    <section class="group" aria-labelledby="site-title">
      <h3 class="label muted" id="site-title">{t.mount.siteAndTime}</h3>
      <dl>
        <dt class="muted">{t.mount.site}</dt>
        <dd>
          <span class="mono">{siteText}</span>
          <span class="caption" class:warning={mount.site_check === "different"} class:muted={mount.site_check !== "different"}>{siteCheck}</span>
        </dd>
        <dt class="muted">{t.mount.time}</dt>
        <dd><span class="mono">{mount.time ? formatDateTime(mount.time, locale) : "—"}</span></dd>
      </dl>
      {#if owner}
        <div class="buttons">
          {#if mount.site_check !== "no_profile_site"}
            <Button busy={busy === "site"} disabled={!!job} onclick={() => void run("site", () => sendMountSite())}>{t.mount.sendSite}</Button>
          {/if}
          <Button busy={busy === "time"} onclick={() => void run("time", sendMountTime)}>{t.mount.sendTime}</Button>
        </div>
      {/if}
    </section>

    <section class="group" aria-labelledby="limits-title">
      <h3 class="label muted" id="limits-title">{t.mount.limits}</h3>
      {#if mount.limits.altitude || mount.limits.meridian}
        {#if mount.limits.altitude}
          <p class="caption">
            {mount.limits.altitude.enabled
              ? t.mount.altitudeOn(degrees(mount.limits.altitude.lower, 0), degrees(mount.limits.altitude.upper, 0))
              : t.mount.altitudeOff}
          </p>
        {/if}
        {#if mount.limits.meridian}
          <p class="caption">{t.mount.meridian(mount.limits.meridian.flip, degrees(mount.limits.meridian.limit, 0))}</p>
        {/if}
      {:else}
        <p class="caption muted">{t.mount.noLimits}</p>
      {/if}
    </section>
  {/if}
</Sheet>

<style>
  .position {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .coordinates {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .readout {
    font-size: 20px;
    line-height: 26px;
    font-weight: 500;
  }
  .running {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h3 {
    margin: 0;
  }
  .fields {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
  }
  .fields > :global(*) {
    min-width: 0;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .buttons > :global(*) {
    flex: 1 1 140px;
  }
  dl {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--space-2) var(--space-4);
    margin: 0;
  }
  dt {
    font-size: 13px;
  }
  dd {
    display: flex;
    flex-direction: column;
    margin: 0;
  }
  p {
    margin: 0;
  }
  .warning {
    color: var(--warning);
  }
</style>
