<script lang="ts">
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";
  import type { IconName } from "./icons";

  let {
    icon,
    title,
    body,
    action,
  }: { icon: IconName; title: string; body: string; action?: Snippet } = $props();
</script>

<section class="empty">
  <span class="badge"><Icon name={icon} size={32} /></span>
  <h2 class="title">{title}</h2>
  <p class="body">{body}</p>
  {#if action}<div class="action">{@render action()}</div>{/if}
</section>

<style>
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-3);
    max-width: 420px;
    margin: var(--space-12) auto;
    text-align: center;
  }
  .badge {
    display: grid;
    place-items: center;
    width: 72px;
    height: 72px;
    margin-bottom: var(--space-2);
    border-radius: 50%;
    background: var(--surface);
    border: 1px solid var(--line);
    color: var(--accent);
  }
  .body {
    color: var(--muted);
  }
  .action {
    margin-top: var(--space-3);
  }
</style>
