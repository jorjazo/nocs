<script lang="ts">
  // A site's position (ADR 0038, 0042): latitude, longitude and elevation typed by
  // hand, or filled from the connected mount's own site or a USB GPS's fix and then
  // edited at will. A source that has nothing to give says why, or is left out
  // (`available`, for the box's first run, where neither is usually connected).
  import Button from "./Button.svelte";
  import NumberField from "./NumberField.svelte";
  import { formatDecimal, formatPlain } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { gpsSource, mountSource, type Source, type SourceProblem } from "../lib/sites";

  let {
    latitude = $bindable(),
    longitude = $bindable(),
    elevation = $bindable(),
    valid = $bindable(true),
    editing = null,
    available = false,
  }: {
    latitude: number | null;
    longitude: number | null;
    elevation: number | null;
    // The three fields hold numbers within range (or nothing).
    valid?: boolean;
    // The saved site being edited, which a source may well be at already.
    editing?: string | null;
    // Show only the sources that have a position to give.
    available?: boolean;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const saved = $derived(live.app.sites?.saved ?? {});
  const active = $derived(live.app.sites?.active ?? null);

  const sources = $derived<{ key: "mount" | "gps"; label: string; name: string; source: Source }[]>([
    { key: "mount", label: t.sites.fromMount, name: t.sites.mount, source: mountSource(live.app.mount, saved, editing) },
    { key: "gps", label: t.sites.fromGps, name: t.sites.gps, source: gpsSource(live.app.gps, saved, editing) },
  ]);
  const shown = $derived(available ? sources.filter(({ source }) => "position" in source) : sources);

  let validity = $state({ latitude: true, longitude: true, elevation: true });
  $effect(() => {
    valid = validity.latitude && validity.longitude && validity.elevation;
  });

  // The fields show a filled position once they are made again.
  let fills = $state(0);

  function fill(source: Source): void {
    if (!("position" in source)) return;
    const position = source.position;
    [latitude, longitude] = [position.latitude, position.longitude];
    if (position.elevation !== null) elevation = position.elevation;
    fills += 1;
  }

  function problemText(problem: SourceProblem): string {
    return t.sites.sourceProblem[problem];
  }

  function describe(name: string, source: Source): string {
    if (!("position" in source)) return problemText(source.problem);
    const { position, near } = source;
    const text = t.sites.sourcePosition(
      name,
      `${formatDecimal(position.latitude, locale, 4)}°`,
      `${formatDecimal(position.longitude, locale, 4)}°`,
      position.elevation === null ? null : `${formatPlain(position.elevation, locale)} m`,
    );
    if (near === null) return text;
    const site = saved[near];
    return `${text} ${near === active ? t.sites.nearActive(site?.name || t.sites.unnamed) : t.sites.nearSaved(site?.name || t.sites.unnamed)}`;
  }
</script>

{#if shown.length > 0}
  <div class="sources">
    {#each shown as { key, label, name, source } (key)}
      <div class="source">
        <Button disabled={!("position" in source)} onclick={() => fill(source)}>{label}</Button>
        <span class="caption muted">{describe(name, source)}</span>
      </div>
    {/each}
  </div>
{/if}
{#key fills}
  <div class="grid">
    <NumberField
      label={t.sites.latitude}
      bind:value={latitude}
      bind:valid={validity.latitude}
      min={-90}
      max={90}
      unit="°"
      hint={t.sites.latitudeHint} />
    <NumberField
      label={t.sites.longitude}
      bind:value={longitude}
      bind:valid={validity.longitude}
      min={-180}
      max={180}
      unit="°"
      hint={t.sites.longitudeHint} />
    <NumberField
      label={t.sites.elevation}
      bind:value={elevation}
      bind:valid={validity.elevation}
      min={-500}
      max={9000}
      unit="m" />
  </div>
{/key}

<style>
  .sources {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .source {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }
</style>
