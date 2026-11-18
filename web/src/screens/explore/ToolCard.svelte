<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "../../components/Icon.svelte";
  import type { IconName } from "../../components/icons";
  import { i18n } from "../../lib/i18n";

  // A tool over Explore's image: a card that folds into its icon, which keeps a dot
  // in the tool's tone so a glance still tells how it stands.
  let {
    icon,
    title,
    open,
    ontoggle,
    tone = null,
    toneText = "",
    side = "left",
    wide = false,
    status,
    children,
  }: {
    icon: IconName;
    title: string;
    open: boolean;
    ontoggle: () => void;
    // How the tool stands, as a dot on the folded icon, said in words for screen readers.
    tone?: "ok" | "accent" | "warning" | "error" | null;
    toneText?: string;
    // Which edge of the image it sits on: it folds towards it.
    side?: "left" | "right";
    // Room for more than a few figures (the sequence's groups).
    wide?: boolean;
    // Beside the title while open.
    status?: Snippet;
    children: Snippet;
  } = $props();

  const t = $derived(i18n.t);
</script>

{#if open}
  <section class="card" class:wide data-overlay aria-label={title}>
    <div class="header">
      <Icon name={icon} size={20} />
      <span class="title">{title}</span>
      {#if status}<span class="status">{@render status()}</span>{/if}
      <button type="button" class="fold" aria-label={t.live.fold(title)} aria-expanded="true" onclick={ontoggle}>
        <Icon name={side === "left" ? "chevronLeft" : "chevronRight"} size={18} />
      </button>
    </div>
    {@render children()}
  </section>
{:else}
  <button
    type="button"
    class="icon"
    aria-label={toneText ? `${t.live.unfold(title)}. ${toneText}` : t.live.unfold(title)}
    aria-expanded="false"
    onclick={ontoggle}>
    <Icon name={icon} />
    {#if tone}<span class="dot {tone}"></span>{/if}
  </button>
{/if}

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    flex: none;
    width: min(280px, 100%);
    padding: var(--space-2) var(--space-3) var(--space-3);
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg) 88%, transparent);
  }
  .card.wide {
    width: min(340px, 100%);
  }
  .header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--touch);
  }
  .title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .status {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    justify-content: flex-end;
  }
  .fold {
    display: grid;
    place-items: center;
    flex: none;
    width: var(--touch);
    height: var(--touch);
    margin-left: auto;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  .status + .fold {
    margin-left: 0;
  }
  .icon {
    position: relative;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg) 72%, transparent);
    color: var(--text);
    cursor: pointer;
  }
  .dot {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .ok {
    background: var(--ok);
  }
  .accent {
    background: var(--accent);
  }
  /* Shaped as well as colored: brass and the warning's yellow are close. */
  .warning {
    border-radius: 0;
    background: var(--warning);
  }
  .error {
    border-radius: 0;
    transform: rotate(45deg);
    background: var(--error);
  }
</style>
