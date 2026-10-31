<script lang="ts">
  // Profile editor (ADR 0011): which device plays each role (driver from the
  // rig's INDI catalog, optional device name, serial port by its stable name),
  // the optics of both trains and the site. Filter names are not here: they
  // belong to each physical wheel (ADR 0016).
  import { untrack } from "svelte";
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import Icon from "../components/Icon.svelte";
  import NumberField from "../components/NumberField.svelte";
  import Toggle from "../components/Toggle.svelte";
  import ScreenHeader from "../components/ScreenHeader.svelte";
  import TextField from "../components/TextField.svelte";
  import { deleteProfile, getProfile, listDrivers, listSerialPorts, putProfile } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { ROLE_ICONS, ROLES } from "../lib/equipment";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { href, router } from "../lib/router.svelte";
  import type { DeviceConfig, Driver, Optics, Profile, Role, SerialPortInfo } from "../lib/types";

  let { id }: { id: string | null } = $props();

  const t = $derived(i18n.t);
  const equipment = $derived(live.app.equipment);
  const connected = $derived(id !== null && equipment?.active === id && equipment.connection !== "disconnected");

  // Catalog groups (INDI's driver XML) offered first for each role.
  const ROLE_GROUPS: Record<Role, readonly string[]> = {
    main_camera: ["CCDs"],
    guide_camera: ["CCDs"],
    mount: ["Telescopes"],
    focuser: ["Focusers"],
    filter_wheel: ["Filter Wheels"],
    power: ["Power", "Auxiliary"],
    weather: ["Weather", "Auxiliary"],
  };

  type DeviceDraft = { driver: string; device: string; port: string };
  type OpticsDraft = { focal_length: number | null; aperture: number | null; reducer: number | null };

  function opticsDraft(optics: Optics | null | undefined): OpticsDraft {
    return {
      focal_length: optics?.focal_length ?? null,
      aperture: optics?.aperture ?? null,
      reducer: optics?.reducer ?? null,
    };
  }

  // The editor is re-created for another profile (App keys it by id).
  let loaded = $state(untrack(() => id === null));
  // Saved back with the edits, so fields this editor does not show (a power
  // box's outputs) survive it.
  let original: Profile | null = null;
  let name = $state("");
  let devices = $state<Partial<Record<Role, DeviceDraft>>>({});
  let imaging = $state<OpticsDraft>(opticsDraft(null));
  let guiding = $state<OpticsDraft>(opticsDraft(null));
  // An off-axis guider or a camera's own guide sensor: guiding uses the imaging optics.
  let throughImaging = $state(false);
  let siteName = $state("");
  let latitude = $state<number | null>(null);
  let longitude = $state<number | null>(null);
  let elevation = $state<number | null>(null);
  // Every number field reports whether its text is valid.
  const NUMBERS = [
    ...["imaging", "guiding"].flatMap((train) => ["focal", "aperture", "reducer"].map((field) => `${train}-${field}`)),
    "latitude",
    "longitude",
    "elevation",
  ];
  let validity = $state<Record<string, boolean>>(Object.fromEntries(NUMBERS.map((key) => [key, true])));

  let drivers = $state<Driver[]>([]);
  let ports = $state<SerialPortInfo[]>([]);
  let loadError = $state("");

  $effect(() => {
    listDrivers()
      .then((list) => (drivers = list))
      .catch((e: unknown) => (loadError = errorText(e, t)));
    listSerialPorts()
      .then((list) => (ports = list))
      .catch(() => {});
    if (id === null) return;
    getProfile(id)
      .then((profile) => {
        original = profile;
        name = profile.name;
        devices = Object.fromEntries(
          Object.entries(profile.devices ?? {}).map(([role, config]) => [
            role,
            { driver: config.driver, device: config.device ?? "", port: config.port ?? "" },
          ]),
        );
        imaging = opticsDraft(profile.imaging);
        guiding = opticsDraft(profile.guiding);
        throughImaging = profile.guiding_through_imaging ?? false;
        siteName = profile.site?.name ?? "";
        latitude = profile.site?.latitude ?? null;
        longitude = profile.site?.longitude ?? null;
        elevation = profile.site?.elevation ?? null;
        loaded = true;
      })
      .catch((e: unknown) => (loadError = errorText(e, t)));
  });

  // -- Drivers -----------------------------------------------------------------------

  // One option per executable: a driver serves many models (all ZWO cameras).
  type Choice = { driver: string; text: string; group: string };
  const choices = $derived.by((): Choice[] => {
    const seen = new Map<string, Choice>();
    for (const entry of drivers) {
      if (!seen.has(entry.driver)) {
        seen.set(entry.driver, { driver: entry.driver, text: `${entry.name} (${entry.driver})`, group: entry.group });
      }
    }
    return [...seen.values()].sort((a, b) => a.text.localeCompare(b.text));
  });

  function groupsFor(role: Role, current: string): { label: string; choices: Choice[] }[] {
    const wanted = ROLE_GROUPS[role];
    const groups = wanted.map((group) => ({ label: group, choices: choices.filter((c) => c.group === group) }));
    const others = choices.filter((c) => !wanted.includes(c.group));
    // A driver missing from the catalog (installed by hand) can still be kept.
    if (current && !choices.some((c) => c.driver === current)) {
      others.unshift({ driver: current, text: current, group: "" });
    }
    return [...groups.filter((g) => g.choices.length > 0), { label: t.editor.otherDrivers, choices: others }];
  }

  // Devices the driver defines right now, from the live INDI state.
  function running(driver: string): string[] {
    return Object.entries(live.app.indi?.devices ?? {})
      .filter(([, device]) => device.properties?.DRIVER_INFO?.elements.DRIVER_EXEC?.value === driver)
      .map(([device]) => device)
      .sort();
  }

  // -- Saving -------------------------------------------------------------------------

  let busy = $state<"save" | "delete" | null>(null);
  let error = $state("");

  const problem = $derived.by(() => {
    if (!name.trim()) return t.editor.needName;
    for (const role of ROLES) {
      if (devices[role] && !devices[role].driver) return t.editor.needDriver(t.roles[role]);
    }
    return "";
  });
  const valid = $derived(!problem && Object.values(validity).every(Boolean));

  // Keeps what the editor does not show (the autofocus sweep) from the optics it edits.
  function optics(draft: OpticsDraft, previous: Optics | null | undefined): Optics | null {
    if (draft.focal_length === null) return null;
    return {
      ...previous,
      focal_length: draft.focal_length,
      aperture: draft.aperture,
      reducer: draft.reducer ?? 1,
    };
  }

  function profile(): Profile {
    const configs = Object.fromEntries(
      ROLES.flatMap((role) => {
        const draft = devices[role];
        if (!draft) return [];
        const config: DeviceConfig = { ...original?.devices?.[role], driver: draft.driver };
        config.device = draft.device.trim() || null;
        config.port = draft.port || null;
        return [[role, config]];
      }),
    );
    return {
      ...original,
      name: name.trim(),
      devices: configs,
      imaging: optics(imaging, original?.imaging),
      guiding: optics(guiding, original?.guiding),
      guiding_through_imaging: throughImaging,
      site:
        latitude !== null && longitude !== null
          ? {
              ...original?.site, // keeps the horizon profile, not edited here yet
              name: siteName.trim(),
              latitude,
              longitude,
              elevation: elevation ?? 0,
            }
          : null,
    };
  }

  // Profile ids are file names: lower-case letters, digits and dashes.
  function newId(): string {
    const base =
      name
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 56) || "profile";
    const taken = new Set(Object.keys(equipment?.profiles ?? {}));
    let candidate = base;
    for (let n = 2; taken.has(candidate); n++) candidate = `${base}-${n}`;
    return candidate;
  }

  async function save(): Promise<void> {
    busy = "save";
    error = "";
    try {
      await putProfile(id ?? newId(), profile());
      router.go({ screen: "rig" });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }

  async function remove(): Promise<void> {
    if (id === null) return;
    busy = "delete";
    error = "";
    try {
      await deleteProfile(id);
      router.go({ screen: "rig" });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

<a class="back" href={href({ screen: "rig" })}><Icon name="chevronLeft" />{t.editor.back}</a>
<ScreenHeader title={id === null ? t.editor.newTitle : t.editor.editTitle} />

{#if loadError}
  <Banner icon="alert" tone="error">{loadError}</Banner>
{:else if !loaded}
  <p class="muted" role="status">{t.boot.loading}</p>
{:else}
  <form
    class="sections"
    onsubmit={(event) => {
      event.preventDefault();
      if (valid) void save();
    }}>
    <fieldset class="section" disabled={!auth.owner}>
      <TextField label={t.editor.name} bind:value={name} maxlength={80} placeholder={t.editor.namePlaceholder} />
      {#if connected}<Banner icon="alert" tone="warning">{t.editor.connectedNote}</Banner>{/if}
    </fieldset>

    <fieldset class="section" disabled={!auth.owner}>
      <legend class="heading">{t.editor.devices}</legend>
      <p class="caption muted">{t.editor.devicesHint}</p>
      <ul class="roles">
        {#each ROLES as role (role)}
          {@const draft = devices[role]}
          <li class="role">
            <div class="role-head">
              <span class="tile"><Icon name={ROLE_ICONS[role]} /></span>
              <span class="role-name">{t.roles[role]}</span>
              {#if draft}
                <Button variant="text" onclick={() => delete devices[role]}>{t.editor.remove}</Button>
              {:else}
                <Button variant="text" onclick={() => (devices[role] = { driver: "", device: "", port: "" })}>
                  <Icon name="plus" size={20} />{t.editor.add(t.roles[role])}
                </Button>
              {/if}
            </div>
            {#if draft}
              {@const names = draft.driver ? running(draft.driver) : []}
              <div class="role-fields">
                <label class="select">
                  <span class="label muted">{t.editor.driver}</span>
                  <select bind:value={draft.driver}>
                    <option value="" disabled>{t.editor.chooseDriver}</option>
                    {#each groupsFor(role, draft.driver) as group (group.label)}
                      <optgroup label={group.label}>
                        {#each group.choices as choice (choice.driver)}
                          <option value={choice.driver}>{choice.text}</option>
                        {/each}
                      </optgroup>
                    {/each}
                  </select>
                </label>
                <TextField
                  label={t.editor.deviceName}
                  bind:value={draft.device}
                  placeholder={names[0] ?? ""}
                  list="{role}-devices"
                  hint={names.length > 0 ? t.editor.running(names.join(", ")) : t.editor.deviceHint} />
                <datalist id="{role}-devices">
                  {#each names as device (device)}<option value={device}></option>{/each}
                </datalist>
                <label class="select">
                  <span class="label muted">{t.editor.port}</span>
                  <select bind:value={draft.port}>
                    <option value="">{t.editor.noPort}</option>
                    {#if draft.port && !ports.some((port) => port.path === draft.port)}
                      <option value={draft.port}>{draft.port} ({t.editor.unplugged})</option>
                    {/if}
                    {#each ports as port (port.path)}
                      <option value={port.path}>{port.path.replace("/dev/serial/by-id/", "")} → {port.device}</option>
                    {/each}
                  </select>
                  <span class="caption muted">{t.editor.portHint}</span>
                </label>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    </fieldset>

    <fieldset class="section" disabled={!auth.owner}>
      <legend class="heading">{t.editor.optics}</legend>
      {#each [{ key: "imaging", label: t.editor.imaging, draft: imaging }, ...(throughImaging ? [] : [{ key: "guiding", label: t.editor.guiding, draft: guiding }])] as train (train.key)}
        <div class="train">
          <h3 class="label">{train.label}</h3>
          <div class="grid">
            <NumberField
              label={t.editor.focalLength}
              bind:value={train.draft.focal_length}
              bind:valid={validity[`${train.key}-focal`]}
              min={1}
              max={100000}
              unit="mm"
              placeholder={t.editor.noOptics} />
            <NumberField
              label={t.editor.aperture}
              bind:value={train.draft.aperture}
              bind:valid={validity[`${train.key}-aperture`]}
              min={1}
              max={10000}
              unit="mm" />
            <NumberField
              label={t.editor.reducer}
              bind:value={train.draft.reducer}
              bind:valid={validity[`${train.key}-reducer`]}
              min={0.1}
              max={10}
              unit="×"
              placeholder="1"
              hint={t.editor.reducerHint} />
          </div>
        </div>
      {/each}
      <Toggle
        label={t.editor.throughImaging}
        hint={t.editor.throughImagingHint}
        checked={throughImaging}
        onchange={(value) => (throughImaging = value)} />
    </fieldset>

    <fieldset class="section" disabled={!auth.owner}>
      <legend class="heading">{t.editor.site}</legend>
      <p class="caption muted">{t.editor.siteHint}</p>
      <TextField label={t.editor.siteName} bind:value={siteName} maxlength={80} />
      <div class="grid">
        <NumberField
          label={t.editor.latitude}
          bind:value={latitude}
          bind:valid={validity.latitude}
          min={-90}
          max={90}
          unit="°"
          hint={t.editor.latitudeHint} />
        <NumberField
          label={t.editor.longitude}
          bind:value={longitude}
          bind:valid={validity.longitude}
          min={-180}
          max={180}
          unit="°"
          hint={t.editor.longitudeHint} />
        <NumberField
          label={t.editor.elevation}
          bind:value={elevation}
          bind:valid={validity.elevation}
          min={-500}
          max={9000}
          unit="m" />
      </div>
    </fieldset>

    {#if auth.owner}
      <div class="actions">
        {#if problem}<p class="caption muted">{problem}</p>{/if}
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="primary" type="submit" wide busy={busy === "save"} disabled={!valid}>{t.editor.save}</Button>
        {#if id !== null}
          <ConfirmButton
            label={t.editor.delete}
            confirmLabel={t.editor.confirmDelete}
            busy={busy === "delete"}
            onconfirm={() => void remove()} />
        {/if}
      </div>
    {/if}
  </form>
{/if}

<style>
  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    margin-top: var(--space-2);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  .sections {
    display: flex;
    flex-direction: column;
    gap: var(--space-8);
    padding-bottom: var(--space-8);
  }
  .section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
  legend {
    padding: 0;
    margin-bottom: var(--space-1);
  }
  .roles {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .role {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-3) 0;
    border-bottom: 1px solid var(--line);
  }
  .role-head {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .tile {
    flex: none;
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-tile);
    background: var(--raised);
  }
  .role-name {
    flex: 1;
    min-width: 0;
    font-size: 17px;
    font-weight: 500;
  }
  .role-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding-left: calc(48px + var(--space-3));
  }
  .select {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .select .label {
    font-size: 15px;
  }
  select {
    min-height: var(--primary-height);
    max-width: 100%;
    padding: 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    text-overflow: ellipsis;
  }
  .train {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }
  .actions {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }
  @media (max-width: 480px) {
    .role-fields {
      padding-left: 0;
    }
  }
</style>
