<script lang="ts">
  // The steps a template makes, read only (ADR 0031: no tree editor in v0.1):
  // start, targets and end, each container with what keeps it going.
  import { i18n } from "../../lib/i18n";
  import { describeContainer, describeNode } from "../../lib/sequence.svelte";
  import type { Container, PowerOutput, Sequence } from "../../lib/types";

  let { sequence, outputs }: { sequence: Sequence; outputs: PowerOutput[] } = $props();
  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const parts = $derived([
    { name: t.sequence.node.start, container: sequence.start },
    { name: t.sequence.node.targets, container: sequence.targets },
    { name: t.sequence.node.end, container: sequence.end },
  ]);
</script>

{#snippet tree(container: Container)}
  <ol>
    {#each container.children ?? [] as child, i (i)}
      <li>
        {#if child.kind === "container"}
          <span class="name">{describeNode(child, t, locale, outputs)}</span>
          {@const watches = describeContainer(child, t, locale)}
          {#if watches}<span class="muted small">{watches}</span>{/if}
          {@render tree(child)}
        {:else}
          {describeNode(child, t, locale, outputs)}
        {/if}
      </li>
    {/each}
  </ol>
{/snippet}

<div class="steps">
  {#each parts as part (part.name)}
    {#if part.container?.children?.length}
      <section>
        <h3>{part.name}</h3>
        {@render tree(part.container)}
      </section>
    {/if}
  {/each}
</div>

<style>
  .steps {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  h3 {
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    font-weight: 600;
    color: var(--muted);
  }
  ol {
    margin: var(--space-1) 0 0;
    padding-left: var(--space-6);
  }
  li {
    padding: 2px 0;
  }
  li > ol {
    border-left: 1px solid var(--line);
  }
  .name {
    font-weight: 500;
  }
  .small {
    display: block;
    font-size: 13px;
    line-height: 18px;
  }
</style>
