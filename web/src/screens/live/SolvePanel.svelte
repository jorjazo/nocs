<script lang="ts">
  // Plate solving from Live view (phase 3.2): solve a frame of the main camera,
  // or solve and sync the mount in one go, then the latest solution: where the
  // frame points, its angle and scale, and how far that is from where the mount
  // thought it pointed. After a plain solve the mount can be synced to it.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import { solve, syncToSolution } from "../../lib/api";
  import type { CameraJob } from "../../lib/camera.svelte";
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { formatDec, formatRa } from "../../lib/mount.svelte";
  import type { CameraField, MountState, SolverState } from "../../lib/types";

  let {
    solver,
    mount,
    field,
    job,
    disabled,
    mountBusy,
    run,
  }: {
    solver: SolverState;
    mount: MountState | null;
    field: CameraField | null;
    // The latest solve job of the camera, running or finished.
    job: CameraJob | null;
    // Not the owner, or the camera is busy.
    disabled: boolean;
    // Another job (a go to, the pad) holds the mount, which must keep still for a frame.
    mountBusy: boolean;
    run: (action: () => Promise<unknown>) => Promise<void>;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const last = $derived(solver.last);

  // Reasons first, so a disabled button always comes with one.
  const solveReason = $derived.by((): string | null => {
    if (!solver.available) return t.solve.unavailable;
    const height = field?.height;
    if (height !== undefined && solver.databases.length > 0) {
      const covered = solver.databases.some((d) => d.min_fov <= height && height <= d.max_fov);
      if (!covered) return t.solve.noDatabase(`${formatDecimal(height, locale, 2)}°`);
    }
    return null;
  });
  const syncReason = $derived.by((): string | null => {
    if (!mount) return t.solve.noMount;
    if (mount.parked) return t.solve.parked;
    if (!mount.tracking) return t.solve.notTracking;
    return null;
  });

  // A failed solve job, explained when the solver says why.
  let dismissed = $state<string | null>(null);
  const failure = $derived.by((): string | null => {
    if (!job || job.info.state !== "failed" || job.id === dismissed) return null;
    const why = solver.failure;
    if (why && why.message === job.info.error) {
      return why.reason === "error" ? `${t.solve.failures.error} ${why.message}` : t.solve.failures[why.reason];
    }
    return job.info.error ?? t.solve.failures.error;
  });

  const canSync = $derived(
    last !== null && last.mount !== null && !last.synced && mount !== null && syncReason === null,
  );

  function arcmin(value: number): string {
    const size = Math.abs(value);
    return size >= 60 ? `${formatDecimal(size / 60, locale, 2)}°` : `${formatDecimal(size, locale, 1)}′`;
  }

  function time(iso: string): string {
    return new Intl.DateTimeFormat(locale, { timeStyle: "medium" }).format(new Date(iso));
  }
</script>

<section class="solve" aria-labelledby="solve-title">
  <div class="header">
    <h2 class="label muted" id="solve-title">{t.solve.title}</h2>
    <div class="buttons">
      <Button disabled={disabled || solveReason !== null || mountBusy} onclick={() => void run(() => solve())}>
        {t.solve.solve}
      </Button>
      <Button
        disabled={disabled || solveReason !== null || syncReason !== null || mountBusy}
        onclick={() => void run(() => solve({ sync: true }))}>
        {t.solve.solveSync}
      </Button>
    </div>
  </div>
  {#if solveReason}
    <p class="caption muted">{solveReason}</p>
  {:else if mount && syncReason}
    <p class="caption muted">{syncReason}</p>
  {:else if !last}
    <p class="caption muted">{t.solve.hint}</p>
  {/if}

  {#if failure && job}
    <Banner icon="alert" tone="error">
      {failure}
      {#snippet action()}
        <Button variant="text" onclick={() => (dismissed = job.id)}>{t.solve.dismiss}</Button>
      {/snippet}
    </Banner>
  {/if}

  {#if last}
    <dl class="result">
      <div class="wide">
        <dt class="label muted">{t.solve.centre}</dt>
        <dd class="mono coordinates"><span>{formatRa(last.ra)}</span> <span>{formatDec(last.dec)}</span></dd>
      </div>
      <div>
        <dt class="label muted">{t.solve.angle}</dt>
        <dd>
          <!-- 359.97° is 0.0°, not 360.0°. -->
          <span class="mono">{formatDecimal((Math.round(last.rotation * 10) / 10) % 360, locale, 1)}°</span>
          {#if last.mirrored}<span class="caption muted">{t.solve.mirrored}</span>{/if}
          <span class="caption muted">{t.solve.angleHint}</span>
        </dd>
      </div>
      <div>
        <dt class="label muted">{t.solve.scale}</dt>
        <dd>
          <span class="mono">{t.solve.arcsecPerPixel(formatDecimal(last.scale, locale, 2))}</span>
          <span class="caption muted mono"
            >{t.solve.field(formatDecimal(last.fov[0], locale, 2), formatDecimal(last.fov[1], locale, 2))}</span>
        </dd>
      </div>
      <div class="wide">
        <dt class="label muted">{t.solve.offset}</dt>
        <dd>
          {#if last.offset}
            <span class="mono">{arcmin(last.offset.angle)}</span>
            <span class="caption muted mono">
              {t.solve.offsetParts(
                (last.offset.ra >= 0 ? t.solve.east : t.solve.west)(arcmin(last.offset.ra)),
                (last.offset.dec >= 0 ? t.solve.north : t.solve.south)(arcmin(last.offset.dec)),
              )}
            </span>
          {:else}
            <span class="caption muted">{t.solve.noOffset}</span>
          {/if}
        </dd>
      </div>
    </dl>
    <p class="caption muted">
      {t.solve.solvedIn(formatDecimal(last.seconds, locale, 1), time(last.taken ?? last.time))}{#if !last.hinted}
        · {t.solve.wholeSky}{/if}
    </p>
    {#if last.synced}
      <span><Chip tone="ok">{t.solve.synced}</Chip></span>
    {:else if canSync}
      <Button disabled={disabled || mountBusy} onclick={() => void run(() => syncToSolution())}>
        {t.solve.sync}
      </Button>
    {/if}
  {/if}
</section>

<style>
  .solve {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
  }
  .solve > :global(.button),
  .solve > span {
    align-self: flex-start;
  }
  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  h2 {
    margin: 0;
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .caption {
    margin: 0;
  }
  .result {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
    margin: 0;
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
  }
  .result > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .result .wide {
    grid-column: 1 / -1;
  }
  dd {
    display: flex;
    flex-direction: column;
    margin: 0;
    font-size: 17px;
    line-height: 24px;
  }
  dd .caption {
    font-size: 13px;
    line-height: 18px;
  }
  .coordinates {
    display: block;
  }
  .coordinates > span {
    white-space: nowrap;
  }
</style>
