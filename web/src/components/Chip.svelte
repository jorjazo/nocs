<script lang="ts" module>
  export type Tone = "ok" | "accent" | "warning" | "error" | "neutral";
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  // A status: a stripe of the tone's color at its left and a word that says it, so
  // status is never color alone. The word stays in the text's color (muted when
  // neutral); the tone's color is only the stripe.
  let { tone = "neutral", children }: { tone?: Tone; children: Snippet } = $props();
</script>

<span class="chip {tone}">{@render children()}</span>

<style>
  .chip {
    --tone: var(--muted);
    display: inline-flex;
    align-items: center;
    min-height: 28px;
    padding: 0 10px 0 8px;
    border-left: 3px solid var(--tone);
    background: var(--surface);
    color: var(--text);
    font-size: 13px;
    line-height: 18px;
    font-weight: 500;
    white-space: nowrap;
  }
  .ok {
    --tone: var(--ok);
  }
  .accent {
    --tone: var(--accent);
  }
  .warning {
    --tone: var(--warning);
  }
  .error {
    --tone: var(--error);
  }
  .neutral {
    color: var(--muted);
  }
</style>
