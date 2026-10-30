<script lang="ts" module>
  export type Tone = "ok" | "accent" | "warning" | "error" | "neutral";
</script>

<script lang="ts">
  import type { Snippet } from "svelte";

  // Status is never color alone: the chip carries a word, and its mark has a
  // different shape per tone (circle, square, diamond, ring).
  let { tone = "neutral", children }: { tone?: Tone; children: Snippet } = $props();
</script>

<span class="chip {tone}">
  <span class="mark" aria-hidden="true"></span>
  {@render children()}
</span>

<style>
  .chip {
    --tone: var(--muted);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 0 12px;
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--tone) var(--tint), var(--surface));
    color: var(--tone);
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
  .mark {
    flex: none;
    width: 8px;
    height: 8px;
    background: currentColor;
    border-radius: 50%;
  }
  .warning .mark {
    border-radius: 1px;
  }
  .error .mark {
    border-radius: 1px;
    transform: rotate(45deg);
  }
  .neutral .mark {
    background: transparent;
    border: 1.5px solid currentColor;
  }
</style>
