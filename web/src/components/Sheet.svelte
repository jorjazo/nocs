<script lang="ts">
  import type { Snippet } from "svelte";
  import { i18n } from "../lib/i18n";
  import Icon from "./Icon.svelte";

  // A modal panel: a bottom sheet on phones, a centered card on wide screens.
  // It opens when mounted; the parent unmounts it from `onclose` (Escape, the
  // close button, a tap outside).
  let {
    title,
    onclose,
    children,
    actions,
  }: { title: string; onclose: () => void; children: Snippet; actions?: Snippet } = $props();

  const id = $props.id();
  let dialog: HTMLDialogElement;

  $effect(() => {
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  });
</script>

<!-- A tap on the backdrop reaches the dialog itself, not its content. -->
<dialog
  bind:this={dialog}
  aria-labelledby="{id}-title"
  onclose={onclose}
  onclick={(event) => {
    if (event.target === dialog) dialog.close();
  }}>
  <div class="sheet">
    <header>
      <h2 class="heading" id="{id}-title">{title}</h2>
      <button type="button" class="close" aria-label={i18n.t.live.close} onclick={() => dialog.close()}>
        <Icon name="close" />
      </button>
    </header>
    <div class="body">{@render children()}</div>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </div>
</dialog>

<style>
  dialog {
    width: 100%;
    max-width: 100%;
    max-height: 90dvh;
    margin: auto 0 0;
    padding: 0;
    border: 1px solid var(--line);
    border-bottom: 0;
    border-radius: var(--radius-card) var(--radius-card) 0 0;
    background: var(--surface);
    color: var(--text);
  }
  dialog::backdrop {
    background: color-mix(in srgb, var(--bg) 70%, transparent);
  }
  .sheet {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-2) var(--margin) calc(var(--space-6) + env(safe-area-inset-bottom));
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .close {
    display: grid;
    place-items: center;
    width: var(--touch);
    height: var(--touch);
    margin-right: calc(-1 * var(--space-3));
    border: 0;
    border-radius: var(--radius-button);
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .actions {
    display: flex;
    gap: var(--space-3);
  }
  .actions > :global(*) {
    flex: 1 1 0;
  }
  @media (min-width: 768px) {
    dialog {
      width: 420px;
      margin: auto;
      border-bottom: 1px solid var(--line);
      border-radius: var(--radius-card);
    }
    .sheet {
      padding: var(--space-4) var(--space-6) var(--space-6);
    }
  }
</style>
