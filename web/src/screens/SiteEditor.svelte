<script lang="ts">
  // A saved site (ADR 0038): its name and position, typed by hand or filled from the
  // mount's own site or a USB GPS's fix (ADR 0042). A new site may become the active
  // one as it is saved. The horizon is kept as it is: the app does not edit it yet.
  import { untrack } from "svelte";
  import Banner from "../components/Banner.svelte";
  import Button from "../components/Button.svelte";
  import ConfirmButton from "../components/ConfirmButton.svelte";
  import Icon from "../components/Icon.svelte";
  import ScreenHeader from "../components/ScreenHeader.svelte";
  import SitePosition from "../components/SitePosition.svelte";
  import TextField from "../components/TextField.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { activateSite, addSite, deleteSite, putSite } from "../lib/api";
  import { auth } from "../lib/auth.svelte";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { href, router } from "../lib/router.svelte";
  import type { Site } from "../lib/types";

  let { id }: { id: string | null } = $props();

  const t = $derived(i18n.t);
  const sites = $derived(live.app.sites ?? null);
  const isActive = $derived(id !== null && sites?.active === id);

  // The editor is re-created for another site (App keys it by id), and starts
  // from the site as the state has it then.
  const original: Site | null = untrack(() => (id !== null ? (live.app.sites?.saved[id] ?? null) : null));
  const missing = untrack(() => id !== null && original === null);
  let name = $state(original?.name ?? "");
  let latitude = $state<number | null>(original?.latitude ?? null);
  let longitude = $state<number | null>(original?.longitude ?? null);
  let elevation = $state<number | null>(original?.elevation ?? null);
  // New sites are usually where the rig stands now.
  let activate = $state(true);
  let positionValid = $state(true);

  const problem = $derived.by(() => {
    if (!name.trim()) return t.sites.needName;
    if (latitude === null || longitude === null) return t.sites.needPosition;
    return "";
  });
  const valid = $derived(!problem && positionValid);

  let busy = $state<"save" | "delete" | null>(null);
  let error = $state("");

  function site(): Site | null {
    if (latitude === null || longitude === null) return null;
    return { ...original, name: name.trim(), latitude, longitude, elevation: elevation ?? 0 };
  }

  async function save(): Promise<void> {
    const edited = site();
    if (!edited) return;
    busy = "save";
    error = "";
    try {
      if (id === null) {
        const created = await addSite(edited);
        if (activate) await activateSite(created);
      } else {
        await putSite(id, edited);
      }
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
      await deleteSite(id);
      router.go({ screen: "rig" });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

<a class="back" href={href({ screen: "rig" })}><Icon name="chevronLeft" />{t.sites.back}</a>
<ScreenHeader title={id === null ? t.sites.newTitle : t.sites.editTitle} />

{#if missing}
  <Banner icon="alert" tone="error">{t.sites.notFound}</Banner>
{:else}
  <form
    class="sections"
    onsubmit={(event) => {
      event.preventDefault();
      if (valid) void save();
    }}>
    <fieldset class="section" disabled={!auth.owner}>
      <TextField label={t.sites.name} bind:value={name} maxlength={80} placeholder={t.sites.namePlaceholder} />
      {#if isActive}<p class="caption muted">{t.sites.isActive}</p>{/if}
    </fieldset>

    <fieldset class="section" disabled={!auth.owner}>
      <legend class="heading">{t.sites.position}</legend>
      <SitePosition bind:latitude bind:longitude bind:elevation bind:valid={positionValid} editing={id} />
    </fieldset>

    {#if id === null}
      <fieldset class="section" disabled={!auth.owner}>
        <Toggle label={t.sites.activate} hint={t.sites.activateHint} checked={activate} onchange={(value) => (activate = value)} />
      </fieldset>
    {/if}

    {#if auth.owner}
      <div class="actions">
        {#if problem}<p class="caption muted">{problem}</p>{/if}
        {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
        <Button variant="primary" type="submit" wide busy={busy === "save"} disabled={!valid}>{t.sites.save}</Button>
        {#if id !== null}
          <ConfirmButton
            label={t.sites.delete}
            confirmLabel={t.sites.confirmDelete}
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
  .actions {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }
</style>
