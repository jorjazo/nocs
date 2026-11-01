<script lang="ts">
  // A night's calibration (ADR 0036): for each group of lights, the darks and
  // flats that match it from any night and the bias the flats need, what is
  // missing, and the two ways to take it: the darks and bias as a sequence left
  // running with the camera covered, the flats with their wizard.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Icon from "../../components/Icon.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { getCalibration, makeCalibrationSequence, startSequence } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatPlain, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type { CalibrationGroup, CalibrationMatch, CalibrationReport, NightInfo } from "../../lib/types";

  let { night }: { night: NightInfo } = $props();

  // The server's defaults for what a set should hold.
  const WANTED = { darks: 20, flats: 20, bias: 50 };

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  let report = $state<CalibrationReport | null>(null);
  let error = $state("");
  let sheet = $state(false);
  let darks = $state<number | null>(WANTED.darks);
  let bias = $state<number | null>(WANTED.bias);
  let warm = $state(true);
  let busy = $state(false);
  let leftOut = $state(0);

  // Again when a frame is saved: the darks sequence and the flats fill the gaps.
  const saved = $derived(live.app.cameras?.main_camera?.last_frame?.id ?? null);
  const running = $derived(live.app.sequence?.run?.state === "running" || live.app.flats?.state === "running");

  $effect(() => {
    const id = night.id;
    void saved;
    const timer = setTimeout(() => void load(id), report === null ? 0 : 2000);
    return () => clearTimeout(timer);
  });

  async function load(id: number): Promise<void> {
    try {
      report = await getCalibration({ night: id });
      error = "";
    } catch (e) {
      error = errorText(e, t);
    }
  }

  const darksMissing = $derived(report?.needs.some((n) => n.kind === "dark" || n.kind === "bias") ?? false);
  const flatsMissing = $derived(report?.needs.some((n) => n.kind === "flat") ?? false);

  function groupName(g: CalibrationGroup): string {
    const parts = [
      g.filter,
      formatSeconds(g.exposure, locale),
      g.temperature !== null ? formatTemperature(g.temperature, locale) : null,
      g.setup.gain !== null ? `G${formatPlain(g.setup.gain, locale)}` : null,
      g.setup.binning !== null && g.setup.binning > 1 ? `${g.setup.binning}×${g.setup.binning}` : null,
    ];
    return parts.filter(Boolean).join(" · ");
  }

  function newest(match: CalibrationMatch): string {
    const night = match.nights[0];
    if (!night) return "";
    return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(new Date(`${night}T12:00:00`));
  }

  async function takeDarks(): Promise<void> {
    if (darks === null || bias === null) return;
    busy = true;
    try {
      const made = await makeCalibrationSequence({ night: night.id, darks, bias, warm });
      leftOut = made.left_out.length;
      await startSequence(made.id);
      sheet = false;
      error = "";
      scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

{#snippet kind(label: string, match: CalibrationMatch, wanted: number)}
  <span class="kind">
    <span class="caption muted">{label}</span>
    {#if match.frames >= wanted}
      <Chip tone="ok">{t.calibration.found(String(match.frames), newest(match))}</Chip>
    {:else if match.frames > 0}
      <Chip tone="warning">{t.calibration.found(`${match.frames}/${wanted}`, newest(match))}</Chip>
    {:else}
      <Chip tone="warning">{t.calibration.missing}</Chip>
    {/if}
  </span>
{/snippet}

<section class="calibration" aria-labelledby="calibration-title">
  <h2 class="heading" id="calibration-title">{t.calibration.title}</h2>
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {#if leftOut > 0}<Banner icon="alert" tone="warning">{t.calibration.leftOut(leftOut)}</Banner>{/if}

  {#if report && report.groups.length === 0}
    <p class="body muted">{t.calibration.noLights}</p>
  {:else if report}
    <p class="body muted">{t.calibration.intro}</p>
    <ul class="groups">
      {#each report.groups as g, i (i)}
        <li>
          <span class="name">{groupName(g)}</span>
          <span class="kinds">
            {@render kind(t.calibration.darks, g.darks, WANTED.darks)}
            {@render kind(t.calibration.flats, g.flats, WANTED.flats)}
            {@render kind(t.calibration.flatBias, g.flat_calibration.frames > 0 ? g.flat_calibration : g.bias, WANTED.bias)}
          </span>
        </li>
      {/each}
    </ul>
    {#if !darksMissing && !flatsMissing}
      <p class="body muted">{t.calibration.complete}</p>
    {/if}
    <div class="actions">
      {#if darksMissing}
        <Button disabled={running} onclick={() => (sheet = true)}>{t.calibration.takeDarks}</Button>
      {/if}
      {#if flatsMissing}
        <Button disabled={running} onclick={() => router.go({ screen: "flats", night: night.id })}>
          {t.calibration.takeFlats}
        </Button>
      {/if}
    </div>
    {#if report.frames > 0}
      <a class="download" href={`${night.zip_url}?calibration=true`} download>
        <Icon name="download" />
        {t.calibration.download}
      </a>
      <p class="caption muted">{t.calibration.downloadHint}</p>
    {/if}
  {/if}
</section>

{#if sheet}
  <Sheet title={t.calibration.sheetTitle} onclose={() => (sheet = false)}>
    <Banner icon="alert" tone="warning">{t.calibration.cover}</Banner>
    <Stepper label={t.calibration.darksCount} bind:value={darks} min={1} max={200} />
    <Stepper label={t.calibration.biasCount} bind:value={bias} min={1} max={500} step={10} />
    <Toggle label={t.calibration.warm} checked={warm} onchange={(on) => (warm = on)} />
    {#snippet actions()}
      <ConfirmButton
        label={t.calibration.start}
        confirmLabel={t.calibration.confirm}
        {busy}
        onconfirm={() => void takeDarks()} />
    {/snippet}
  </Sheet>
{/if}

<style>
  .calibration {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin-bottom: var(--space-6);
  }
  .groups {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
  }
  .groups li {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
  }
  .groups li + li {
    border-top: 1px solid var(--line);
  }
  .name {
    font-weight: 600;
  }
  .kinds {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }
  .kind {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .download {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    align-self: flex-start;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
</style>
