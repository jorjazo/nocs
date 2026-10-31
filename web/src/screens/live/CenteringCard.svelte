<script lang="ts">
  // The running centring, or the latest one (stage 3.3): the target, where it
  // stands, and every frame with how far it landed from the target. Shown in
  // Live view and in the mount's sheet, which starts it.
  import Chip from "../../components/Chip.svelte";
  import type { Tone } from "../../components/Chip.svelte";
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { formatDec, formatRa } from "../../lib/mount.svelte";
  import type { CenteringAttempt, CenteringState } from "../../lib/types";

  let { centering }: { centering: CenteringState } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  function arcmin(value: number): string {
    const size = Math.abs(value);
    return size >= 60 ? `${formatDecimal(size / 60, locale, 2)}°` : `${formatDecimal(size, locale, 1)}′`;
  }

  const solved = $derived(centering.attempts.filter((a) => a.error !== null));
  const last = $derived(solved.at(-1)?.error ?? null);

  const status = $derived.by((): { tone: Tone; text: string } => {
    switch (centering.state) {
      case "running":
        return {
          tone: "accent",
          text: t.center.phase(
            t.center.phases[centering.phase ?? "slewing"],
            Math.min(centering.attempts.length + 1, centering.max_attempts),
            centering.max_attempts,
          ),
        };
      case "succeeded":
        return { tone: "ok", text: t.center.centred };
      case "cancelled":
        return { tone: "neutral", text: t.center.cancelled };
      default:
        return { tone: "error", text: t.center.notCentred };
    }
  });

  // Why it failed, in this language when the attempts say it.
  const failure = $derived.by((): string | null => {
    if (centering.state !== "failed") return null;
    const frames = centering.attempts.length;
    if (frames === centering.max_attempts) {
      return last
        ? t.center.gaveUp(arcmin(last.angle), frames, arcmin(centering.tolerance))
        : t.center.neverSolved(frames);
    }
    return centering.error;
  });

  function line(attempt: CenteringAttempt): string {
    if (attempt.error) {
      const parts = t.solve.offsetParts(
        (attempt.error.ra >= 0 ? t.solve.east : t.solve.west)(arcmin(attempt.error.ra)),
        (attempt.error.dec >= 0 ? t.solve.north : t.solve.south)(arcmin(attempt.error.dec)),
      );
      return `${arcmin(attempt.error.angle)} · ${parts}`;
    }
    return attempt.failure ? t.center.notSolved(t.solve.failures[attempt.failure.reason]) : "—";
  }
</script>

<section class="centering" aria-labelledby="centering-title">
  <div class="header">
    <h3 class="label muted" id="centering-title">{t.center.title}</h3>
    <Chip tone={status.tone}>{status.text}</Chip>
  </div>
  <p class="caption muted">
    <span class="mono">{formatRa(centering.target.ra)} {formatDec(centering.target.dec)}</span>
    · {t.center.within(arcmin(centering.tolerance))}
    · {centering.method === "sync" ? t.center.bySync : t.center.byOffset}
  </p>
  {#if centering.attempts.length > 0}
    <ol>
      {#each centering.attempts as attempt, index (index)}
        <li>
          <span class="label muted">{t.center.frame(index + 1)}</span>
          <span class={attempt.error ? "mono" : "caption muted"}>{line(attempt)}</span>
          {#if attempt.synced}<span class="caption muted">{t.center.synced}</span>{/if}
        </li>
      {/each}
    </ol>
  {/if}
  {#if failure}<p class="caption error">{failure}</p>{/if}
</section>

<style>
  .centering {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
  }
  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  h3,
  p {
    margin: 0;
  }
  ol {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
  }
  .error {
    color: var(--error);
  }
</style>
