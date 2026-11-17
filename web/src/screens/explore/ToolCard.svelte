<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "../../components/Icon.svelte";
  import type { IconName } from "../../components/icons";
  import { i18n } from "../../lib/i18n";

  // A tool over Explore's image (ADR 0054): a card with rounded corners that folds
  // into its icon, which keeps a dot in the tool's tone so a glance still tells how
  // it stands.
  let {
    icon,
    title,
    open,
    ontoggle,
    tone = null,
    toneText = "",
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
    // Beside the title while open.
    status?: Snippet;
    children: Snippet;
  } = $props();

  const t = $derived(i18n.t);
</script>

{#if open}
  <section class="card" data-overlay aria-label={title}>
    <div class="header">
      <Icon name={icon} size={20} />
      <span class="title">{title}</span>
      {#if status}<span class="status">{@render status()}</span>{/if}
      <button type="button" class="fold" aria-label={t.live.fold(title)} aria-expanded="true" onclick={ontoggle}>
        <Icon name="chevronLeft" size={18} />
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
    width: min(280px, calc(50cqw - var(--space-4)));
    min-width: 220px;
    max-height: calc(100cqh - var(--space-6));
    overflow-y: auto;
    padding: var(--space-2) var(--space-3) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: color-mix(in srgb, var(--bg) 84%, transparent);
    backdrop-filter: blur(6px);
  }
  .header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 36px;
  }
  .title {
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
    width: 36px;
    height: 36px;
    margin-left: auto;
    border: 0;
    border-radius: var(--radius-button);
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
    border-radius: var(--radius-button);
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
  .warning {
    background: var(--warning);
  }
  .error {
    background: var(--error);
  }
</style>
