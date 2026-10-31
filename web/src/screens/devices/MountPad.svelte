<script lang="ts">
  // The slew pad: the mount moves only while an arrow is held (two at once move
  // diagonally) and stops when it is let go, the page goes to the background or
  // the link drops; the server enforces it too (ADR 0015). Arrow keys work on a
  // keyboard. Shown in the mount's sheet and, folded, in Live view.
  import { untrack } from "svelte";
  import Icon from "../../components/Icon.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import type { IconName } from "../../components/icons";
  import { i18n } from "../../lib/i18n";
  import { type Direction, PadLink } from "../../lib/mount.svelte";
  import type { MountState } from "../../lib/types";

  let {
    mount,
    disabled = false,
    reason = null,
  }: {
    mount: MountState;
    disabled?: boolean;
    // Why it is disabled, when that is not obvious.
    reason?: string | null;
  } = $props();

  const t = $derived(i18n.t);
  const link = new PadLink();
  let rate = $state<string | null>(untrack(() => mount.slew_rate));
  const rates = $derived(mount.slew_rates.map((value) => ({ value, label: value })));

  // The link is open while the pad may be used.
  $effect(() => {
    if (disabled) return;
    link.open();
    return () => link.close();
  });
  $effect(() => {
    link.setRate(rate);
  });
  // Anything that takes the user's hand away lets go of the arrows.
  $effect(() => {
    const away = () => link.releaseAll();
    const hidden = () => {
      if (document.visibilityState !== "visible") away();
    };
    window.addEventListener("blur", away);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("blur", away);
      document.removeEventListener("visibilitychange", hidden);
    };
  });

  const KEYS: Record<string, Direction> = {
    ArrowUp: "north",
    ArrowDown: "south",
    ArrowLeft: "east",
    ArrowRight: "west",
  };

  function typing(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
  }

  function keydown(event: KeyboardEvent): void {
    const direction = KEYS[event.key];
    if (!direction || disabled || typing(event.target)) return;
    event.preventDefault();
    if (!event.repeat) link.press(direction);
  }

  function keyup(event: KeyboardEvent): void {
    const direction = KEYS[event.key];
    if (direction) link.release(direction);
  }

  function down(event: PointerEvent, direction: Direction): void {
    if (disabled) return;
    event.preventDefault();
    link.press(direction);
    // Keeps the release with this button when the finger slides off it.
    try {
      (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    } catch {
      // A pointer the browser no longer tracks: its release still comes.
    }
  }

  const buttons: { direction: Direction; icon: IconName }[] = [
    { direction: "north", icon: "up" },
    { direction: "east", icon: "left" },
    { direction: "west", icon: "right" },
    { direction: "south", icon: "down" },
  ];

  const status = $derived(link.status);
  const message = $derived.by((): string | null => {
    if (reason) return reason;
    if (status?.latched) return t.mount.padLatched;
    if (!disabled && !link.connected) return t.mount.padOffline;
    if (mount.moved_by && link.held.length === 0) return t.mount.movedBy(mount.moved_by);
    return null;
  });
</script>

<svelte:window onkeydown={keydown} onkeyup={keyup} />

<div class="pad">
  <div class="cross" role="group" aria-label={t.mount.pad}>
    {#each buttons as { direction, icon } (direction)}
      <button
        type="button"
        class="arrow {direction}"
        class:held={link.held.includes(direction)}
        aria-label={t.mount[direction]}
        aria-pressed={link.held.includes(direction)}
        {disabled}
        onpointerdown={(event) => down(event, direction)}
        onpointerup={() => link.release(direction)}
        onpointercancel={() => link.release(direction)}
        onlostpointercapture={() => link.release(direction)}
        onkeydown={(event) => {
          if ((event.key === " " || event.key === "Enter") && !event.repeat && !disabled) {
            event.preventDefault();
            link.press(direction);
          }
        }}
        onkeyup={(event) => {
          if (event.key === " " || event.key === "Enter") link.release(direction);
        }}
        oncontextmenu={(event) => event.preventDefault()}>
        <Icon name={icon} size={28} />
        <span class="letter">{t.mount.letters[direction]}</span>
      </button>
    {/each}
    <span class="center mono" aria-hidden="true">{rate ?? ""}</span>
  </div>
  {#if rates.length > 1 && rate !== null}
    <SegmentedControl label={t.mount.rate} options={rates} value={rate} {disabled} onchange={(value) => (rate = value)} />
  {/if}
  <p class="caption" class:warning={status?.latched && !reason} class:muted={!status?.latched || reason} role="status">
    {message ?? t.mount.padHint}
  </p>
</div>

<style>
  .pad {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }
  .cross {
    display: grid;
    grid-template-columns: repeat(3, 72px);
    grid-template-rows: repeat(3, 72px);
    gap: var(--space-2);
    justify-content: center;
  }
  .arrow {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0;
    border: 1px solid var(--line);
    border-radius: var(--radius-button);
    background: var(--raised);
    color: var(--text);
    cursor: pointer;
    /* Holding must not scroll, select or open the long-press menu. */
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
  }
  .arrow:disabled {
    cursor: default;
    opacity: 0.45;
  }
  .arrow.held {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 22%, var(--raised));
  }
  .letter {
    font-size: 12px;
    line-height: 14px;
    font-weight: 600;
    color: var(--muted);
  }
  .north {
    grid-area: 1 / 2;
  }
  .east {
    grid-area: 2 / 1;
  }
  .west {
    grid-area: 2 / 3;
  }
  .south {
    grid-area: 3 / 2;
  }
  .center {
    grid-area: 2 / 2;
    display: grid;
    place-items: center;
    border: 1px dashed var(--line);
    border-radius: 50%;
    color: var(--muted);
    font-size: 13px;
  }
  .warning {
    color: var(--warning);
  }
  p {
    margin: 0;
    text-align: center;
  }
</style>
