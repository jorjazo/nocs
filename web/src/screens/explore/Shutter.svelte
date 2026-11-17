<script lang="ts">
  // The screen's primary action: take a frame, or stop what the camera is
  // doing. Its ring fills with the exposure's progress.
  let {
    running,
    progress,
    label,
    disabled = false,
    onclick,
  }: {
    running: boolean;
    // 0 to 1; null while unknown (downloading, processing).
    progress: number | null;
    label: string;
    disabled?: boolean;
    onclick: () => void;
  } = $props();

  const RADIUS = 34;
  const LENGTH = 2 * Math.PI * RADIUS;
</script>

<button type="button" class="shutter" class:running aria-label={label} {disabled} {onclick}>
  <svg viewBox="0 0 76 76" aria-hidden="true">
    <circle class="track" cx="38" cy="38" r={RADIUS} />
    {#if running}
      <circle
        class="progress"
        class:unknown={progress === null}
        cx="38"
        cy="38"
        r={RADIUS}
        stroke-dasharray={LENGTH}
        stroke-dashoffset={progress === null ? LENGTH * 0.75 : LENGTH * (1 - Math.min(1, Math.max(0, progress)))} />
    {/if}
  </svg>
  <span class="mark"></span>
</button>

<style>
  .shutter {
    position: relative;
    display: grid;
    place-items: center;
    width: 76px;
    height: 76px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    cursor: pointer;
  }
  .shutter:disabled {
    cursor: default;
    opacity: 0.55;
  }
  svg {
    position: absolute;
    inset: 0;
    transform: rotate(-90deg);
  }
  circle {
    fill: none;
    stroke-width: 4;
  }
  .track {
    stroke: var(--text);
  }
  .running .track {
    stroke: var(--line);
  }
  .progress {
    stroke: var(--accent);
    stroke-linecap: round;
    transition: stroke-dashoffset 900ms linear;
  }
  .unknown {
    transform-origin: center;
    animation: spin 1.2s linear infinite;
  }
  .mark {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: var(--accent);
    transition:
      border-radius 150ms,
      width 150ms,
      height 150ms;
  }
  .running .mark {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: var(--error);
  }
  .shutter:active:not(:disabled) .mark {
    filter: brightness(1.15);
  }
  @keyframes spin {
    to {
      transform: rotate(1turn);
    }
  }
</style>
