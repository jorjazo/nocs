<script lang="ts">
  // Guiding over Explore's image (ADR 0054): what PHD2 is doing, the RMS of its last
  // 100 steps in RA, Dec and in total, a button to start or stop guiding, and the
  // way to the guiding screen for the rest (connecting, looping, calibrating again,
  // dithering). Folded, its icon keeps a dot in the state's tone.
  import Button from "../../components/Button.svelte";
  import Chip, { type Tone } from "../../components/Chip.svelte";
  import { cancelJob, startGuiding, stopGuiding } from "../../lib/api";
  import { formatDecimal } from "../../lib/format";
  import { guidingActive } from "../../lib/guiding.svelte";
  import { i18n } from "../../lib/i18n";
  import { href } from "../../lib/router.svelte";
  import type { GuidingState, JobInfo } from "../../lib/types";
  import ToolCard from "./ToolCard.svelte";

  let {
    guiding,
    jobs,
    owner,
    rig,
    open,
    ontoggle,
    run,
  }: {
    guiding: GuidingState | null;
    jobs: Record<string, JobInfo> | null | undefined;
    owner: boolean;
    // A guide camera and a mount are connected.
    rig: boolean;
    open: boolean;
    ontoggle: () => void;
    run: (action: () => Promise<unknown>) => Promise<void>;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  const reachable = $derived(guiding?.phd2.connected ?? false);
  const state = $derived(guiding?.app_state ?? null);
  const active = $derived(guidingActive(guiding));
  // A start of guiding (calibrating first) or a dither, from any client.
  const job = $derived.by((): string | null => {
    for (const [id, info] of Object.entries(jobs ?? {})) {
      if (info.state === "running" && (info.kind === "guide" || info.kind === "dither")) return id;
    }
    return null;
  });

  const chip = $derived.by((): { tone: Tone; text: string } => {
    if (!reachable) return { tone: "error", text: t.guiding.unreachable };
    const text = state ? t.guiding.state[state] : t.guiding.unknown;
    if (state === "Guiding") return guiding?.settling ? { tone: "accent", text: t.guiding.settling } : { tone: "ok", text };
    if (state === "LostLock") return { tone: "error", text };
    if (state === "Calibrating" || state === "Looping" || state === "Selected") return { tone: "accent", text };
    return { tone: "neutral", text };
  });
  const dot = $derived(chip.tone === "neutral" ? null : chip.tone);

  const blocked = $derived.by(() => {
    if (!owner) return t.guiding.observer;
    if (!reachable) return t.guiding.unreachable;
    if (!rig) return t.guiding.noRig;
    return null;
  });

  // In arcseconds with the pixel scale, else in guide camera pixels.
  const stats = $derived(guiding?.stats ?? null);
  function rms(arcsec: number | null | undefined, px: number | null | undefined): string {
    if (arcsec != null) return `${formatDecimal(arcsec, locale, 2)}″`;
    if (px != null) return `${formatDecimal(px, locale, 2)} px`;
    return "—";
  }
  const figures = $derived([
    { name: t.guiding.ra, value: rms(stats?.rms_ra, stats?.rms_ra_px) },
    { name: t.guiding.dec, value: rms(stats?.rms_dec, stats?.rms_dec_px) },
    { name: t.guiding.total, value: rms(stats?.rms_total, stats?.rms_total_px) },
  ]);

  function stop(): Promise<void> {
    return run(async () => {
      if (job) await cancelJob(job);
      await stopGuiding();
    });
  }
</script>

<ToolCard icon="guide" title={t.guiding.title} {open} {ontoggle} tone={dot} toneText={chip.text}>
  {#snippet status()}<Chip tone={chip.tone}>{chip.text}</Chip>{/snippet}
  <dl class="figures">
    {#each figures as figure (figure.name)}
      <div>
        <dt class="caption muted">{figure.name}</dt>
        <dd class="mono">{figure.value}</dd>
      </div>
    {/each}
  </dl>
  <p class="caption muted">{t.live.guidingSteps(stats?.steps ?? 0)}</p>
  <div class="row">
    {#if active || job}
      <Button variant="danger" disabled={!owner || !reachable} onclick={() => void stop()}>{t.live.guideStop}</Button>
    {:else}
      <Button variant="primary" disabled={blocked !== null} onclick={() => void run(() => startGuiding())}>
        {t.live.guideStart}
      </Button>
    {/if}
    <a class="link" href={href({ screen: "guiding" })}>{t.live.guidingScreen}</a>
  </div>
  {#if blocked && !active}<p class="caption muted">{blocked}</p>{/if}
</ToolCard>

<style>
  .figures {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-2);
    margin: 0;
  }
  .figures div {
    display: flex;
    flex-direction: column;
  }
  dd {
    margin: 0;
    font-size: 17px;
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .link {
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
  p {
    margin: 0;
  }
</style>
