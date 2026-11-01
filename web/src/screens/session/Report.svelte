<script lang="ts">
  // A session's report (stage 5.15, #/session/<id>): its window and how it
  // ended, integration per filter, the HFR of every frame with the autofocus
  // runs, the temperatures, the focus runs, the events, and the frames as CSV.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import { sessionCsvUrl, sessionReport } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { formatDateTime, formatDecimal, formatDuration, formatPlain, formatTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { router } from "../../lib/router.svelte";
  import { describeEvent } from "../../lib/sequence.svelte";
  import type { SessionReport } from "../../lib/types";
  import TimeChart, { type Series } from "./TimeChart.svelte";

  let { id }: { id: number } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  let report = $state<SessionReport | null>(null);
  let error = $state("");
  let missing = $state(false);

  $effect(() => {
    sessionReport(id)
      .then((found) => (report = found))
      .catch((e: unknown) => {
        if (e instanceof Error && "status" in e && e.status === 404) missing = true;
        else error = errorText(e, t);
      });
  });

  const seconds = (iso: string) => new Date(iso).getTime() / 1000;
  const start = $derived(report ? seconds(report.session.started) : 0);
  const end = $derived(report ? start + report.duration : 0);
  const shown = $derived(report ? (report.session.outcome ?? (report.session.ended ? "completed" : "running")) : "running");
  const clouds = $derived(report?.frames.filter((f) => f.clouds).length ?? 0);
  const lights = $derived(report?.frames.filter((f) => f.frame_type === "light") ?? []);

  const hfr = $derived<Series[]>([
    {
      label: t.report.hfr,
      style: "dots",
      points: lights.flatMap((f) =>
        f.hfr === null
          ? []
          : [{ t: seconds(f.started), v: f.hfr, title: `${f.filter ?? ""} · HFR ${formatDecimal(f.hfr, locale, 2)}${f.clouds ? ` · ${t.report.clouds}` : ""}` }],
      ),
    },
  ]);
  const focusMarkers = $derived(
    (report?.focus ?? []).map((run) => ({
      t: seconds(run.time),
      title: `${t.sequence.autofocus} ${formatTime(run.time, locale)}${run.reason ? ` · ${run.reason}` : ""}`,
    })),
  );
  const temperatures = $derived<Series[]>(
    report
      ? [
          {
            label: t.report.focuser,
            style: "solid" as const,
            points: report.temperatures.flatMap((s) => (s.focuser === null ? [] : [{ t: seconds(s.time), v: s.focuser }])),
          },
          {
            label: t.report.ambient,
            style: "dashed" as const,
            points: report.temperatures.flatMap((s) => (s.ambient === null ? [] : [{ t: seconds(s.time), v: s.ambient }])),
          },
        ].filter((s) => s.points.length > 1)
      : [],
  );

  const number = (value: number | null, digits = 2) => (value === null ? "—" : formatDecimal(value, locale, digits));
</script>

<ScreenHeader title={t.report.title}>
  {#snippet trailing()}
    <Button variant="text" onclick={() => router.go({ screen: "session" })}>
      <Icon name="chevronLeft" size={20} />{t.report.back}
    </Button>
  {/snippet}
</ScreenHeader>

{#if missing}
  <EmptyState icon="session" title={t.report.missing} body="" />
{:else if error}
  <Banner icon="alert" tone="error">{error}</Banner>
{:else if !report}
  <p class="muted" role="status">{t.report.loading}</p>
{:else}
  <div class="report">
    <section class="head">
      <span class="muted small">{formatDateTime(report.session.started, locale)}{report.session.profile ? ` · ${report.session.profile}` : ""}</span>
      <h2>{report.session.name}</h2>
      <p class="muted small">
        {t.report.window(
          formatTime(report.session.started, locale),
          report.session.ended ? formatTime(report.session.ended, locale) : t.report.running,
          formatDuration(report.duration),
        )}
        · {shown === "running" ? t.session.states.running : t.session.states[shown]}
      </p>
      {#if report.session.error}<Banner icon="alert" tone="error">{t.report.error}: {report.session.error}</Banner>{/if}
      {#if report.session.restarts > 0}<p class="muted small">{t.session.restarts(report.session.restarts)}</p>{/if}
    </section>

    <section class="totals">
      <div class="card total">
        <span class="muted small">{t.report.integration}</span>
        <span class="mono value">{formatDuration(report.integration)}</span>
      </div>
      <div class="card total">
        <span class="muted small">{t.report.frames}</span>
        <span class="mono value">{lights.length - clouds}</span>
      </div>
      <div class="card total">
        <span class="muted small">{t.report.clouds}</span>
        <span class="mono value">{clouds}</span>
      </div>
      <div class="card total">
        <span class="muted small">{t.report.failures}</span>
        <span class="mono value">{report.failures}</span>
        {#if report.recoveries}<span class="muted small">{t.report.recovered(report.recoveries)}</span>{/if}
      </div>
    </section>

    {#if report.filters.length}
      <section aria-labelledby="per-filter">
        <h3 id="per-filter">{t.report.perFilter}</h3>
        <table>
          <thead>
            <tr>
              <th scope="col">{t.report.filter}</th>
              <th scope="col" class="num">{t.report.frames}</th>
              <th scope="col" class="num">{t.report.integration}</th>
              <th scope="col" class="num">{t.report.hfr}</th>
              <th scope="col" class="num">{t.report.guideRms}</th>
            </tr>
          </thead>
          <tbody>
            {#each report.filters as row (row.filter)}
              <tr>
                <th scope="row">{row.filter ?? t.report.noFilter}</th>
                <td class="num mono">{row.frames}{row.clouds ? ` (+${row.clouds})` : ""}</td>
                <td class="num mono">{formatDuration(row.integration)}</td>
                <td class="num mono">{number(row.hfr)}</td>
                <td class="num mono">{row.guide_rms === null ? "—" : `${number(row.guide_rms)}″`}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}

    {#if hfr[0]?.points.length}
      <section aria-labelledby="hfr-chart">
        <h3 id="hfr-chart">{t.report.hfrChart}</h3>
        <TimeChart label={t.report.hfrLabel(hfr[0].points.length)} unit="px" series={hfr} markers={focusMarkers} {start} {end} digits={1} />
      </section>
    {/if}

    {#if temperatures.length}
      <section aria-labelledby="temperature-chart">
        <h3 id="temperature-chart">{t.report.temperatureChart}</h3>
        <TimeChart label={t.report.temperatureLabel} unit="°C" series={temperatures} {start} {end} digits={1} />
      </section>
    {/if}

    {#if report.focus.length}
      <section aria-labelledby="focus-runs">
        <h3 id="focus-runs">{t.report.focus}</h3>
        <ul class="list">
          {#each report.focus as run, i (i)}
            <li>
              <span class="mono muted time">{formatTime(run.time, locale)}</span>
              <span class="small">
                {run.position !== null ? t.report.focusAt(formatPlain(run.position, locale), number(run.hfr)) : t.sequence.autofocus}
                {run.filter ? ` · ${run.filter}` : ""} · {run.reason ?? t.report.focusStep}
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <section aria-labelledby="report-events">
      <h3 id="report-events">{t.report.events}</h3>
      <ol class="list">
        {#each report.events as event, i (i)}
          <li>
            <span class="mono muted time">{formatTime(event.time, locale)}</span>
            <span class="small">{describeEvent(event, t, locale)}</span>
          </li>
        {/each}
      </ol>
    </section>

    <a class="csv" href={sessionCsvUrl(report.session.id)} download>
      <Icon name="download" size={20} />{t.report.csv}
    </a>
  </div>
{/if}

<style>
  .report {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-3);
    padding-bottom: var(--space-6);
  }
  h2,
  p {
    margin: 0;
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: 15px;
    line-height: 22px;
  }
  .head {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .totals {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: var(--space-2);
  }
  .total {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
  }
  .value {
    font-size: 20px;
    line-height: 26px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  th,
  td {
    padding: var(--space-2) var(--space-1);
    border-bottom: 1px solid var(--line);
    text-align: left;
  }
  thead th {
    color: var(--muted);
    font-weight: 400;
    font-size: 13px;
  }
  .num {
    text-align: right;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--line);
  }
  .time {
    flex: none;
    min-width: 44px;
    font-size: 13px;
    white-space: nowrap;
  }
  .csv {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 500;
    text-decoration: none;
  }
</style>
