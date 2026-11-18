<script lang="ts">
  // A site's position (ADR 0038, 0042): latitude, longitude and elevation typed by
  // hand (decimal degrees or degrees, minutes and seconds), pasted (a Google Maps link
  // or a pair of coordinates, `lib/position`), or filled from the connected mount's own
  // site or a USB GPS's fix, and then edited at will. A source that has nothing to give says why, or is left out
  // (`available`, for the box's first run, where neither is usually connected).
  import { untrack } from "svelte";
  import Button from "./Button.svelte";
  import NumberField from "./NumberField.svelte";
  import TextField from "./TextField.svelte";
  import { ApiError, expandMapsLink } from "../lib/api";
  import { formatDecimal, formatPlain } from "../lib/format";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { parseAngle, readPasted, type LatLon } from "../lib/position";
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

  const id = $props.id();
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

  // What was pasted, read as it changes; a short link waits for the box to expand it,
  // and only the latest one counts.
  let pasted = $state("");
  type PasteNote = { kind: "busy" | "read" | "error"; text: string };
  let pasteNote = $state<PasteNote | null>(null);
  let pasteToken = 0;

  function fillPasted(position: LatLon): void {
    [latitude, longitude] = [position.latitude, position.longitude];
    fills += 1;
    pasteNote = {
      kind: "read",
      text: t.sites.pasteRead(`${formatDecimal(position.latitude, locale, 6)}°`, `${formatDecimal(position.longitude, locale, 6)}°`),
    };
  }

  $effect(() => {
    const text = pasted;
    return untrack(() => readPaste(text));
  });

  function readPaste(text: string): (() => void) | undefined {
    const token = ++pasteToken;
    if (text.trim() === "") {
      pasteNote = null;
      return;
    }
    const reading = readPasted(text);
    if ("position" in reading) {
      fillPasted(reading.position);
      return;
    }
    // Typing is not done yet: say what is wrong only once it pauses.
    pasteNote = null;
    const timer = setTimeout(() => {
      if (token !== pasteToken) return;
      if ("problem" in reading) {
        pasteNote = { kind: "error", text: t.sites.pasteProblem[reading.problem] };
        return;
      }
      pasteNote = { kind: "busy", text: t.sites.pasteExpanding };
      expandMapsLink(reading.short).then(
        (url) => {
          if (token !== pasteToken) return;
          const long = readPasted(url);
          if ("position" in long) fillPasted(long.position);
          else pasteNote = { kind: "error", text: t.sites.pasteProblem.noPosition };
        },
        (e: unknown) => {
          if (token !== pasteToken) return;
          const status = e instanceof ApiError ? e.status : 0;
          const text = status === 502 ? t.sites.pasteOffline : status === 422 ? t.sites.pasteDead : t.sites.pasteFailed;
          pasteNote = { kind: "error", text };
        },
      );
    }, 400);
    return () => clearTimeout(timer);
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
        <Button disabled={!("position" in source)} describedby="{id}-{key}" onclick={() => fill(source)}>{label}</Button>
        <span class="caption muted" id="{id}-{key}">{describe(name, source)}</span>
      </div>
    {/each}
  </div>
{/if}
<TextField
  label={t.sites.paste}
  bind:value={pasted}
  autocomplete="off"
  placeholder={t.sites.pastePlaceholder}
  error={pasteNote?.kind === "error" ? pasteNote.text : undefined}
  hint={pasteNote && pasteNote.kind !== "error" ? pasteNote.text : t.sites.pasteHint} />
{#key fills}
  <div class="grid">
    <NumberField
      label={t.sites.latitude}
      bind:value={latitude}
      bind:valid={validity.latitude}
      min={-90}
      max={90}
      parse={(text) => parseAngle(text, "latitude")}
      inputmode="text"
      unit="°"
      hint={t.sites.latitudeHint} />
    <NumberField
      label={t.sites.longitude}
      bind:value={longitude}
      bind:valid={validity.longitude}
      min={-180}
      max={180}
      parse={(text) => parseAngle(text, "longitude")}
      inputmode="text"
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
