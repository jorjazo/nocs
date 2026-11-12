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
  import { getCalibration, makeCalibrationSequence, planCalibrationSequence, startSequence } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatDuration, formatPlain, formatSeconds, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import type {
    CalibrationDarkGroup,
    CalibrationGroup,
    CalibrationMatch,
    CalibrationPlan,
    CalibrationReport,
    NightInfo,
  } from "../../lib/types";

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
  // The dark groups chosen in the sheet, by key, and what they would take.
  let chosen = $state<string[]>([]);
  let plan = $state<CalibrationPlan | null>(null);
  let planning = $state(false);
  let planned = 0;

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

  function groupName(g: CalibrationGroup | CalibrationDarkGroup): string {
    const parts = [
      "filter" in g ? g.filter : null,
      formatSeconds(g.exposure, locale),
      g.temperature !== null ? formatTemperature(g.temperature, locale) : null,
      g.setup.gain !== null ? `G${formatPlain(g.setup.gain, locale)}` : null,
      "filter" in g || g.setup.offset === null ? null : `O${formatPlain(g.setup.offset, locale)}`,
      g.setup.binning !== null && g.setup.binning > 1 ? `${g.setup.binning}×${g.setup.binning}` : null,
    ];
    return parts.filter(Boolean).join(" · ");
  }

  const covered = (g: CalibrationDarkGroup): boolean => g.missing_darks === 0 && g.missing_bias === 0;

  function darkHint(g: CalibrationDarkGroup): string {
    const filters = g.filters.filter((f) => f !== null);
    const what = [t.calibration.lights(g.lights), filters.join(", "), g.targets.join(", ")].filter(Boolean);
    if (covered(g)) {
      what.push(t.calibration.covered(g.darks));
    } else {
      what.push(t.calibration.takes(g.missing_darks, g.missing_bias));
    }
    const line = what.join(" · ");
    if (g.reason === "few_lights") return `${line}. ${t.calibration.fewLights}`;
    if (g.reason === "warm") return `${line}. ${t.calibration.warmLights}`;
    return line;
  }

  function openSheet(): void {
    chosen = (report?.dark_groups ?? []).filter((g) => g.reason === null && !covered(g)).map((g) => g.key);
    plan = null;
    sheet = true;
  }

  function choose(key: string, on: boolean): void {
    chosen = on ? [...chosen, key] : chosen.filter((k) => k !== key);
  }

  // What the choice takes, again as groups and counts change (not as the night's
  // object is replaced by a state update).
  const nightId = $derived(night.id);
  $effect(() => {
    if (!sheet || darks === null || bias === null) return;
    const body = { night: nightId, darks, bias, warm, groups: [...chosen] };
    planning = true;
    const timer = setTimeout(() => void loadPlan(body), 250);
    return () => clearTimeout(timer);
  });

  async function loadPlan(body: { night: number; darks: number; bias: number; warm: boolean; groups: string[] }): Promise<void> {
    const call = ++planned;
    try {
      const found = await planCalibrationSequence(body);
      if (call !== planned) return;
      plan = found;
      error = "";
    } catch (e) {
      if (call !== planned) return;
      plan = null;
      error = errorText(e, t);
    } finally {
      if (call === planned) planning = false;
    }
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
      const made = await makeCalibrationSequence({ night: night.id, darks, bias, warm, groups: [...chosen] });
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
        <Button disabled={running} onclick={openSheet}>{t.calibration.takeDarks}</Button>
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
    <h3 class="label muted subsection">{t.calibration.groups}</h3>
    <p class="caption muted">{t.calibration.groupsHint}</p>
    <div class="choices">
      {#each plan?.dark_groups ?? report?.dark_groups ?? [] as g (g.key)}
        <Toggle
          label={groupName(g)}
          hint={darkHint(g)}
          checked={!covered(g) && chosen.includes(g.key)}
          disabled={covered(g)}
          onchange={(on) => choose(g.key, on)} />
      {/each}
    </div>
    <Stepper label={t.calibration.darksCount} bind:value={darks} min={1} max={200} />
    <Stepper label={t.calibration.biasCount} bind:value={bias} min={1} max={500} step={10} />
    <Toggle label={t.calibration.warm} checked={warm} onchange={(on) => (warm = on)} />
    <p class="body total" aria-live="polite">
      {#if plan === null}
        {planning ? t.calibration.planning : ""}
      {:else if plan.frames === 0}
        {t.calibration.nothing}
      {:else}
        {t.calibration.total(plan.frames, formatDuration(plan.seconds))}
      {/if}
    </p>
    {#if plan && plan.left_out.length > 0}
      <Banner icon="alert" tone="warning">{t.calibration.leftOut(plan.left_out.length)}</Banner>
    {/if}
    {#snippet actions()}
      <ConfirmButton
        label={t.calibration.start}
        confirmLabel={t.calibration.confirm}
        disabled={planning || plan === null || plan.frames === 0}
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
  .subsection {
    margin: var(--space-2) 0 0;
  }
  .choices {
    display: flex;
    flex-direction: column;
  }
  .total {
    min-height: 1.5em;
    font-weight: 600;
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
