<script lang="ts">
  // A readout tile that opens its editor: label, a live value (numbers in mono,
  // words in sans, which is narrower), and an optional detail line.
  let {
    label,
    value,
    detail,
    word = false,
    disabled = false,
    onclick,
  }: {
    label: string;
    value: string;
    detail?: string;
    word?: boolean;
    disabled?: boolean;
    onclick: () => void;
  } = $props();
</script>

<button type="button" class="tile" {disabled} {onclick}>
  <span class="label">{label}</span>
  <span class="value" class:word>{value}</span>
  {#if detail}<span class="detail">{detail}</span>{/if}
</button>

<style>
  .tile {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    min-height: 68px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
    background: var(--surface);
    text-align: left;
    cursor: pointer;
  }
  .tile:disabled {
    cursor: default;
  }
  .tile:disabled .value {
    color: var(--muted);
  }
  .tile:active:not(:disabled) {
    background: var(--raised);
  }
  .label {
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
    font-weight: 500;
  }
  .value {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 20px;
    line-height: 26px;
    font-weight: 500;
  }
  .word {
    font-family: var(--font-sans);
  }
  .detail {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 16px;
  }
</style>
