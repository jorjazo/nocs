<script lang="ts">
  // Rig: the active profile and its connection on top, always in view; below it the
  // sections in four groups (optics and devices, the site, the box, settings), each
  // opened and closed on its own (docs/ux.md §7, "Rig"). Two columns on a PC.
  import { tick, untrack, type Snippet } from "svelte";
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import Chip from "../components/Chip.svelte";
  import EmptyState from "../components/EmptyState.svelte";
  import Icon from "../components/Icon.svelte";
  import ScreenHeader from "../components/ScreenHeader.svelte";
  import Section from "../components/Section.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import { connectProfile, disconnectEquipment, getProfile } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { connectionTone, ROLES, roles } from "../lib/equipment";
  import { errorText } from "../lib/errors";
  import { i18n, LANGUAGE_NAMES } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { LOCALES, prefs } from "../lib/prefs.svelte";
  import { href, router } from "../lib/router.svelte";
  import AccessSection from "./rig/AccessSection.svelte";
  import DevicesSection from "./rig/DevicesSection.svelte";
  import NetworkSection from "./rig/NetworkSection.svelte";
  import TailscaleSection from "./rig/TailscaleSection.svelte";
  import SiteSection from "./rig/SiteSection.svelte";
  import StorageSection from "./rig/StorageSection.svelte";
  import SystemSection from "./rig/SystemSection.svelte";
  import TrainsSection from "./rig/TrainsSection.svelte";
  import UpdatesSection from "./rig/UpdatesSection.svelte";
  import type { RigSection } from "../lib/rigsections";
  import type { Profile, Role, RoleState } from "../lib/types";

  const t = $derived(i18n.t);

  const equipment = $derived(live.app.equipment);

  // -- Profile and connection ---------------------------------------------------

  const profiles = $derived(
    Object.entries(equipment?.profiles ?? {}).sort(([, a], [, b]) => a.name.localeCompare(b.name)),
  );
  let picked = $state<string | null>(null);
  const profileId = $derived(
    picked !== null && equipment?.profiles[picked] ? picked : (equipment?.active ?? profiles[0]?.[0] ?? null),
  );
  const connection = $derived(equipment?.connection ?? "disconnected");

  // The optics are in the profile, which only the owner may read.
  let profile = $state<Profile | null>(null);
  $effect(() => {
    const id = profileId;
    const owner = auth.owner;
    profile = null;
    if (id === null || !owner) return;
    let current = true;
    getProfile(id)
      .then((loaded) => {
        if (current) profile = loaded;
      })
      .catch(() => {});
    return () => {
      current = false;
    };
  });

  // Until a profile is connected the state lists no roles: show the selected
  // profile's devices instead, all offline.
  const roleList = $derived.by((): [Role, RoleState][] => {
    const current = equipment ? roles(equipment) : [];
    if (current.length > 0 || !profile) return current;
    return ROLES.flatMap((role): [Role, RoleState][] => {
      const config = profile?.devices?.[role];
      if (!config) return [];
      const device = config.device ?? null;
      return [[role, { driver: config.driver, device, status: "disconnected", error: null, unresponsive_since: null }]];
    });
  });
  const devicesByRole = $derived(Object.fromEntries(roleList) as Partial<Record<Role, RoleState>>);
  const anyError = $derived(roleList.some(([, device]) => device.status === "error"));

  let busy = $state<"connect" | "disconnect" | null>(null);
  let actionError = $state("");

  async function run(kind: NonNullable<typeof busy>, action: () => Promise<void>): Promise<void> {
    busy = kind;
    actionError = "";
    try {
      await action();
    } catch (e) {
      actionError = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  // The box's group shows only where there is something of the box to show.
  const hasBox = $derived(
    !!live.app.system ||
      !!live.app.storage ||
      !!live.app.network ||
      (auth.owner && (!!live.app.updates || !!live.app.tailscale)),
  );

  // #/rig/<section> opens that section and scrolls to it, once the state is in.
  // The profile arrives later and grows the page above it (the trains, the devices),
  // so for a moment each such change scrolls to it again; Safari keeps no anchor.
  let anchor: { section: RigSection; until: number } | null = null;
  function scrollTo(section: RigSection): void {
    void tick().then(() => document.getElementById(`rig-${section}`)?.scrollIntoView({ block: "start" }));
  }
  $effect(() => {
    const route = router.route;
    if (route.screen !== "rig" || !route.section || !live.synced) return;
    const section = route.section;
    untrack(() => prefs.setSectionOpen(section, true));
    anchor = { section, until: Date.now() + 2000 };
    scrollTo(section);
  });
  $effect(() => {
    void profile;
    void roleList.length;
    if (anchor && Date.now() < anchor.until) scrollTo(anchor.section);
  });
</script>

<ScreenHeader title={t.rig.title}>
  {#snippet trailing()}
    {#if profiles.length > 0 && profileId !== null}
      <label class="picker">
        <span class="visually-hidden">{t.rig.profile}</span>
        <select
          value={profileId}
          disabled={!auth.owner || connection !== "disconnected"}
          onchange={(event) => (picked = event.currentTarget.value)}>
          {#each profiles as [id, summary] (id)}
            <option value={id}>{summary.name}</option>
          {/each}
        </select>
        <Icon name="chevronDown" size={20} />
      </label>
    {/if}
  {/snippet}
</ScreenHeader>

{#snippet group(id: string, title: string, body: Snippet)}
  <section class="group" aria-labelledby="group-{id}">
    <h2 class="group-title label" id="group-{id}">{title}</h2>
    <div class="card group-card">{@render body()}</div>
  </section>
{/snippet}

{#snippet site()}
  <!-- Observers do not get the sites (ADR 0047). -->
  {#if live.app.sites}
    {#snippet body()}<SiteSection />{/snippet}
    {@render group("site", t.rig.groups.site, body)}
  {/if}
{/snippet}

{#snippet box()}
  {#if hasBox}
    {#snippet body()}
      <SystemSection />
      <StorageSection />
      <NetworkSection />
      <TailscaleSection />
      <UpdatesSection />
    {/snippet}
    {@render group("box", t.rig.groups.box, body)}
  {/if}
{/snippet}

{#snippet settings()}
  {#snippet body()}
    <AccessSection />
    <Section id="screen" title={t.prefs.title} summary={LANGUAGE_NAMES[prefs.locale]}>
      <div class="pref">
        <span class="label muted">{t.language.label}</span>
        <SegmentedControl
          label={t.language.label}
          options={LOCALES.map((value) => ({ value, label: LANGUAGE_NAMES[value] }))}
          value={prefs.locale}
          onchange={(value) => prefs.setLocale(value)} />
      </div>
    </Section>
    <a class="advanced" href={href({ screen: "dev" })}>
      <span class="text">
        <span class="heading">{t.rig.advanced}</span>
        <span class="summary">{t.rig.advancedHint}</span>
      </span>
      <Icon name="chevronRight" />
    </a>
  {/snippet}
  {@render group("settings", t.rig.groups.settings, body)}
{/snippet}

{#if !live.synced}
  <p class="loading muted" role="status">{t.boot.loading}</p>
{:else if equipment && profiles.length === 0}
  <EmptyState icon="rig" title={t.rig.noProfiles} body={t.rig.noProfilesBody}>
    {#snippet action()}
      {#if auth.owner}
        <Button variant="primary" onclick={() => router.go({ screen: "profile", id: null })}>{t.rig.newProfile}</Button>
      {/if}
    {/snippet}
  </EmptyState>
  <div class="layout">
    <div class="column">
      {#snippet servicesBody()}
        <DevicesSection roles={[]} {connection} profileId={null} />
      {/snippet}
      {@render group("equipment", t.rig.groups.equipment, servicesBody)}
      {@render site()}
    </div>
    <div class="column">
      {@render box()}
      {@render settings()}
    </div>
  </div>
{:else if equipment}
  <div class="layout">
    <div class="column">
      <section class="card connection" aria-labelledby="connection-title">
        <div class="line">
          <h2 class="heading" id="connection-title">{t.rig.equipment}</h2>
          <Chip tone={equipment.error ? "error" : connectionTone(connection)}>{t.connection[connection]}</Chip>
        </div>
        {#if equipment.error || actionError}
          <p class="error">{actionError || equipment.error}</p>
        {/if}
        {#if auth.owner && profileId !== null}
          {@const id = profileId}
          <div class="buttons">
            {#if connection === "disconnected"}
              <Button variant="primary" wide busy={busy === "connect"} onclick={() => run("connect", () => connectProfile(id))}>
                {t.rig.connect}
              </Button>
            {:else}
              {#if anyError}
                <Button variant="primary" busy={busy === "connect"} onclick={() => run("connect", () => connectProfile(id))}>
                  {t.rig.retry}
                </Button>
              {/if}
              <Button
                busy={busy === "disconnect"}
                disabled={connection === "disconnecting"}
                onclick={() => run("disconnect", disconnectEquipment)}>
                {t.rig.disconnect}
              </Button>
            {/if}
          </div>
          <div class="links">
            <a href={href({ screen: "profile", id })}>{t.rig.editProfile}</a>
            <a href={href({ screen: "profile", id: null })}>{t.rig.newProfile}</a>
          </div>
        {/if}
      </section>

      {#snippet equipmentBody()}
        <TrainsSection {profile} devices={devicesByRole} />
        <DevicesSection roles={roleList} {connection} {profileId} />
      {/snippet}
      {@render group("equipment", t.rig.groups.equipment, equipmentBody)}

      {@render site()}
    </div>
    <div class="column">
      {@render box()}
      {@render settings()}
    </div>
  </div>
{:else}
  <Banner icon="alert" tone="warning">{t.boot.loading}</Banner>
{/if}

<style>
  .loading {
    padding: var(--space-8) 0;
  }
  .layout {
    display: grid;
    gap: var(--space-6);
    padding-bottom: var(--space-8);
  }
  .column {
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
    min-width: 0;
  }
  /* A PC: the rig on the left, the box and settings on the right. */
  @media (min-width: 1200px) {
    .layout {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;
      max-width: 1600px;
    }
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .group-title {
    margin: 0;
    padding: 0 var(--space-1);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .group-card {
    padding-top: 0;
    padding-bottom: 0;
  }
  .connection {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .buttons {
    display: flex;
    gap: var(--space-3);
    flex-wrap: wrap;
    margin-top: var(--space-1);
  }
  .error {
    color: var(--error);
    overflow-wrap: anywhere;
  }
  .links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-6);
  }
  .links a {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  .pref {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .picker {
    position: relative;
    display: inline-flex;
    align-items: center;
    color: var(--text);
  }
  .picker select {
    appearance: none;
    min-height: 48px;
    max-width: 60vw;
    padding: 0 44px 0 var(--space-4);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    font-weight: 500;
    text-overflow: ellipsis;
    cursor: pointer;
  }
  .picker select:disabled {
    cursor: default;
  }
  .picker :global(.icon) {
    position: absolute;
    right: 14px;
    pointer-events: none;
  }
  /* Looks like a section's header, but leads to another screen. */
  .advanced {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    min-height: 64px;
    padding: var(--space-3) 0;
    border-top: 1px solid var(--line);
    color: var(--text);
    text-decoration: none;
  }
  .advanced .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .advanced .summary {
    color: var(--muted);
    font-size: 15px;
    line-height: 20px;
  }
  .advanced :global(.icon) {
    flex: none;
    color: var(--muted);
  }
</style>
