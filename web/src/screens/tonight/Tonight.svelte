<script lang="ts">
  // Tonight, the home screen (docs/ux.md §1): the night and how things stand now.
  // The get-ready checklist (connect, focus, polar align) comes first while a step
  // is left; its next step carries the one primary button: the first one not done
  // that can run, and one that cannot says why and where to fix it, from what the
  // server says each step needs (ADR 0041). Then the night from sunset to sunrise
  // with the darkness left, where the mount points, the weather, the actuators, the
  // location and time, and the host; the checklist goes last once all is done. Each
  // is a card that opens and closes, and says how it stands when closed.
  import Button from "../../components/Button.svelte";
  import NightBar from "../../components/NightBar.svelte";
  import RigStatus from "../../components/RigStatus.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import Section from "../../components/Section.svelte";
  import WeatherCard from "../../components/WeatherCard.svelte";
  import { connectProfile } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { applies, blockerText, blockersOf, fixRoute, statuses, type Blocker, type StepKey, type StepStatus } from "../../lib/checklist";
  import { errorText } from "../../lib/errors";
  import { calibratedFor } from "../../lib/focus";
  import { formatDecimal, formatDuration, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href, router, type Route } from "../../lib/router.svelte";
  import { darkLeft, phase, type DarkLeft } from "../../lib/sky/night";
  import { prefs } from "../../lib/prefs.svelte";
  import { siteKey, tonight } from "../../lib/tonight.svelte";
  import { arrange, type TonightSection } from "../../lib/tonightsections";
  import { formatAngle } from "../polar/angle";
  import ActuatorsCard from "./ActuatorsCard.svelte";
  import HostCard from "./HostCard.svelte";
  import LocationCard from "./LocationCard.svelte";
  import PointingCard from "./PointingCard.svelte";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const equipment = $derived(live.app.equipment ?? null);
  const profile = $derived(equipment?.active ?? null);
  const site = $derived(siteKey(live.app.sites));
  const weather = $derived(live.app.weather ?? null);
  const forecast = $derived(live.app.forecast ?? null);
  const almanac = $derived(tonight.almanac);

  $effect(() => {
    void tonight.load(site);
  });

  // The clock the cards read; the almanac is asked for again every minute.
  let now = $state(Date.now());
  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 15_000);
    const reload = setInterval(() => void tonight.load(site), 60_000);
    return () => {
      clearInterval(tick);
      clearInterval(reload);
    };
  });

  // -- The night -------------------------------------------------------------------

  const nightTitle = $derived.by(() => {
    if (!almanac) return t.tonight.title;
    const day = new Date(`${almanac.night}T12:00:00Z`);
    const text = new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }).format(day);
    return t.tonight.nightOf(text);
  });
  const darkFor = $derived(
    almanac?.dark ? (Date.parse(almanac.dark.end) - Date.parse(almanac.dark.start)) / 1000 : null,
  );
  const moonPhase = $derived(almanac ? phase(almanac.moon.phase) : null);
  // A thin Moon does not brighten the sky: then the dark window is all that counts.
  const moonMatters = $derived(!!almanac && almanac.moon.fraction > 0.1);
  const left = $derived(almanac ? darkLeft(almanac.dark, moonMatters ? almanac.dark_moonless : null, now) : null);
  const leftText = $derived(darkText(left));
  // The forecast runs to the end of the dark window (else of the night).
  const forecastUntil = $derived(almanac ? Date.parse(almanac.dark?.end ?? almanac.end) : now + 12 * 3600_000);

  function darkText(value: DarkLeft | null): string | null {
    if (!value) return null;
    if (value.when === "before") return t.tonight.darkIn(formatDuration(value.in), formatDuration(value.length));
    if (value.when === "after") return t.tonight.darkOver;
    const text = t.tonight.darkLeft(formatDuration(value.left));
    // Within a minute of the whole: the Moon takes nothing from what is left.
    if (value.moonless === null || value.left - value.moonless < 60) return text;
    const moonless = value.moonless < 60 ? t.tonight.darkLeftMoonUp : t.tonight.darkLeftMoonless(formatDuration(value.moonless));
    return `${text} · ${moonless}`;
  }

  // -- Checklist ----------------------------------------------------------------------

  interface Step {
    key: StepKey;
    title: string;
    detail: string;
    done: boolean;
    action: string;
    route: Route;
    blockers: Blocker[];
  }

  const nightStart = $derived(almanac ? Date.parse(almanac.start) : now - 12 * 3600_000);
  const preparation = $derived(live.app.preparation ?? null);
  const savedSites = $derived(Object.keys(live.app.sites?.saved ?? {}).length);
  const profileName = $derived(profile ? (equipment?.profiles[profile]?.name ?? profile) : null);
  const connection = $derived(equipment?.connection ?? "disconnected");
  let connecting = $state(false);
  let connectError = $state("");

  const steps = $derived.by((): Step[] => {
    const connected = connection === "connected";
    const list: Step[] = [
      {
        key: "connect",
        title: t.tonight.steps.connect,
        detail: connected && profileName
          ? t.tonight.connected(profileName)
          : connection === "connecting" || connecting
            ? t.tonight.connecting
            : t.tonight.notConnected,
        done: connected,
        action: t.tonight.openRig,
        route: { screen: "rig" },
        blockers: [],
      },
    ];
    if (applies(preparation, "focus")) {
      const run = live.app.autofocus ?? null;
      const tonightRun = run?.finished && Date.parse(run.finished) > nightStart ? run : null;
      const focused = tonightRun?.state === "succeeded";
      // Calibrating focuses too (ADR 0044): offered instead until the focuser has a
      // calibration for this profile, and it goes straight to the calibration.
      const calibrated = calibratedFor(live.app.focuser?.calibration, profile);
      list.push({
        key: "focus",
        title: t.tonight.steps.focus,
        detail: focused
          ? t.tonight.focused(formatTime(tonightRun.finished ?? "", locale), tonightRun.hfr === null ? "—" : formatDecimal(tonightRun.hfr, locale, 2))
          : !calibrated && live.app.focuser
            ? t.tonight.notCalibrated
            : tonightRun
              ? t.tonight.focusFailed
              : t.tonight.notFocused,
        done: focused,
        action: calibrated || !live.app.focuser ? t.tonight.focus : t.tonight.calibrate,
        route: calibrated || !live.app.focuser ? { screen: "focus" } : { screen: "focus-calibration" },
        blockers: blockersOf(preparation, "focus", savedSites),
      });
    }
    // Plate solving needs focused stars: polar alignment comes after focusing.
    if (applies(preparation, "polar")) {
      const run = live.app.polar_alignment ?? null;
      const tonightRun = run?.finished && Date.parse(run.finished) > nightStart && run.axis ? run : null;
      const aligned = !!tonightRun?.aligned;
      const off = tonightRun?.axis ? formatAngle(tonightRun.axis.total, locale) : "";
      list.push({
        key: "polar",
        title: t.tonight.steps.polar,
        detail: aligned
          ? t.tonight.polarAligned(formatTime(tonightRun?.finished ?? "", locale), off)
          : tonightRun
            ? t.tonight.polarOff(off)
            : t.tonight.notPolarAligned,
        done: aligned,
        action: t.tonight.polarAlign,
        route: { screen: "polar" },
        blockers: blockersOf(preparation, "polar", savedSites),
      });
    }
    return list;
  });

  const status = $derived(statuses(steps.map((s) => ({ done: s.done, blocked: s.blockers.length > 0 }))));
  // The connect step connects the profile last used right here, besides leading to Rig.
  const canConnect = $derived(auth.owner && profile !== null && connection === "disconnected" && !connecting);

  async function connect(): Promise<void> {
    if (!profile) return;
    connecting = true;
    connectError = "";
    try {
      await connectProfile(profile);
    } catch (e) {
      connectError = errorText(e, t);
    } finally {
      connecting = false;
    }
  }

  function statusText(value: StepStatus | undefined): string {
    return value === "done" ? t.tonight.stepDone : value === "blocked" ? t.tonight.stepBlocked : t.tonight.stepPending;
  }

  // -- The cards ----------------------------------------------------------------------

  const prepared = $derived(steps.every((step) => step.done));
  // Observers do not see where the box is (ADR 0047).
  const order = $derived(arrange(prepared).filter((section) => section !== "location" || auth.owner));
  // The checklist is open while something is left: opened or closed by hand, it
  // keeps that only until it is done, or undone, again.
  let prepChoice: boolean | null = $state(null);
  $effect(() => {
    void prepared;
    prepChoice = null;
  });
  const prepOpen = $derived(prepChoice ?? !prepared);

  function open(section: TonightSection): boolean {
    return section === "preparation" ? prepOpen : prefs.tonightOpen(section);
  }
  function toggle(section: TonightSection): (open: boolean) => void {
    return (value) => {
      if (section === "preparation") prepChoice = value;
      else prefs.setTonightOpen(section, value);
    };
  }
</script>

<ScreenHeader title={t.tabs.tonight}>
  {#snippet trailing()}<RigStatus />{/snippet}
</ScreenHeader>

<div class="screen">
  {#each order as section (section)}
    {#if section === "preparation"}
      {@render preparationCard()}
    {:else if section === "night"}
      {@render nightCard()}
    {:else if section === "pointing"}
      <PointingCard {almanac} {now} open={open("pointing")} ontoggle={toggle("pointing")} />
    {:else if section === "weather" && (weather || forecast)}
      <WeatherCard {weather} {forecast} until={forecastUntil} {now} open={open("weather")} ontoggle={toggle("weather")} />
    {:else if section === "actuators"}
      <ActuatorsCard {now} open={open("actuators")} ontoggle={toggle("actuators")} />
    {:else if section === "location"}
      <LocationCard {now} open={open("location")} ontoggle={toggle("location")} />
    {:else if section === "host"}
      <HostCard open={open("host")} ontoggle={toggle("host")} />
    {/if}
  {/each}
</div>

{#snippet nightCard()}
  <Section scope="tonight" id="night" title={nightTitle} summary={leftText} open={open("night")} ontoggle={toggle("night")}>
    {#if almanac}
      <NightBar {almanac} {now} />
      <div class="facts">
        <div>
          <span class="label muted">{t.tonight.dark}</span>
          {#if almanac.dark && darkFor !== null}
            <span class="readout">{formatTime(almanac.dark.start, locale)}–{formatTime(almanac.dark.end, locale)}</span>
            <span class="muted">
              {almanac.darkness === "astronomical" ? formatDuration(darkFor) : t.tonight.darkest(t.tonight.darkness[almanac.darkness ?? "civil"])}
            </span>
          {:else}
            <span class="readout">—</span>
            <span class="muted">{t.tonight.noDark}</span>
          {/if}
        </div>
        <div>
          <span class="label muted">{t.tonight.moon}</span>
          <span class="readout">{moonPhase ? t.tonight.phases[moonPhase] : "—"}</span>
          <span class="muted">
            {t.tonight.lit(formatDecimal(almanac.moon.fraction * 100, locale, 0))}
            {#if almanac.moon.rise}· {t.tonight.rises(formatTime(almanac.moon.rise, locale))}{/if}
            {#if almanac.moon.set}· {t.tonight.sets(formatTime(almanac.moon.set, locale))}{/if}
          </span>
        </div>
      </div>
      {#if leftText}<p class="left" data-dark={left?.when}>{leftText}</p>{/if}
      {#if almanac.dark_moonless.length && moonMatters}
        <p class="caption muted">
          {t.tonight.moonless(
            almanac.dark_moonless.map((i) => `${formatTime(i.start, locale)}–${formatTime(i.end, locale)}`).join(", "),
          )}
        </p>
      {/if}
    {:else if tonight.missingSite}
      <p class="muted">{t.tonight.noSite}</p>
      {#if auth.owner}
        <div><Button onclick={() => router.go({ screen: "rig", section: "site" })}>{t.tonight.openRig}</Button></div>
      {/if}
    {:else if tonight.error}
      <p class="muted">{errorText(tonight.error, t)}</p>
      <div><Button onclick={() => tonight.load(site, true)}>{t.tonight.retry}</Button></div>
    {:else}
      <p class="muted" role="status">{t.tonight.loading}</p>
    {/if}
  </Section>
{/snippet}

{#snippet preparationCard()}
  <Section
    scope="tonight"
    id="preparation"
    title={t.tonight.checklist}
    summary={t.tonight.prepared(steps.filter((step) => step.done).length, steps.length)}
    open={open("preparation")}
    ontoggle={toggle("preparation")}>
    <ol class="steps">
      {#each steps as step, i (step.key)}
        {@const stepState = status[i]}
        {@const offered = stepState === "next" || stepState === "ready"}
        <li class:done={step.done} class:blocked={stepState === "blocked"} data-step={step.key} data-status={stepState}>
          <span class="mark" aria-hidden="true">{step.done ? "✓" : ""}</span>
          <div class="text">
            <span class="title">{step.title}</span>
            <span class="muted">{step.detail}</span>
            {#if step.key === "connect" && connectError}<span class="error">{connectError}</span>{/if}
            {#if stepState === "blocked"}
              <ul class="blockers">
                {#each step.blockers as blocker (`${blocker.reason}:${blocker.role}`)}
                  <li>
                    {blockerText(t, blocker)}
                    {#if blocker.fix && auth.owner}
                      <a href={href(fixRoute(blocker.fix))}>{t.preparation.fixes[blocker.fix]}</a>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
          {#if offered && step.key === "connect" && canConnect && profileName}
            <div class="actions">
              <Button variant={stepState === "next" ? "primary" : "text"} onclick={() => void connect()}>
                {t.tonight.connectProfile(profileName)}
              </Button>
              <Button variant="text" onclick={() => router.go(step.route)}>{step.action}</Button>
            </div>
          {:else if offered && !(step.key === "connect" && (connecting || connection === "connecting"))}
            <Button variant={stepState === "next" ? "primary" : "text"} onclick={() => router.go(step.route)}>{step.action}</Button>
          {/if}
          <span class="visually-hidden">{statusText(stepState)}</span>
        </li>
      {/each}
    </ol>
  </Section>
{/snippet}

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-4);
  }
  p {
    margin: 0;
  }
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
  }
  .left {
    font-weight: 500;
  }
  .steps {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .steps > li {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 56px;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--line);
  }
  .steps > li:first-child {
    border-top: none;
  }
  .mark {
    flex: none;
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: var(--radius-full);
    border: 2px solid var(--muted);
    font-size: 13px;
    line-height: 1;
  }
  .done .mark {
    border-color: var(--ok);
    background: var(--ok);
    color: var(--bg);
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .title {
    font-weight: 500;
  }
  .blocked .mark {
    border-style: dashed;
  }
  .blockers {
    list-style: none;
    margin: var(--space-1) 0 0;
    padding: 0;
    font-size: 14px;
    line-height: 20px;
  }
  .blockers a {
    white-space: nowrap;
  }
  .actions {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }
  .error {
    color: var(--error);
  }
</style>
