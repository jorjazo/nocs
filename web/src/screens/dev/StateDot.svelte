<script lang="ts">
  import type { PropertyState } from "../../lib/types";

  let { state }: { state: PropertyState } = $props();
</script>

<span class="dot {state.toLowerCase()}" title={state} aria-label="State: {state}"></span>

<style>
  .dot {
    display: inline-block;
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--line);
  }
  .ok {
    background: var(--ok);
  }
  .busy {
    background: var(--warning);
    border-radius: 2px;
  }
  .alert {
    background: var(--error);
    border-radius: 0;
    transform: rotate(45deg);
  }
</style>
