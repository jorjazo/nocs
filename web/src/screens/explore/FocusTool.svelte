<script lang="ts">
  // The focuser over Explore's image (ADR 0054): where it stands, a speed (half, once
  // or twice the step set in its sheet), in and out, and autofocus started at once
  // with the profile's sweep, with the way to its curve. The position opens the
  // focuser's sheet, where the step is set. Video focuses by hand, on its sharpness
  // number (`children`): no autofocus there, which measures stars.
  import Button from "../../components/Button.svelte";
  import PillSwitch from "../../components/PillSwitch.svelte";
  import { startAutofocus } from "../../lib/api";
  import { capture, FOCUS_SPEEDS } from "../../lib/camera.svelte";
  import { speedStep } from "../../lib/explore";
  import { formatPlain, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { href } from "../../lib/router.svelte";
  import type { Snippet } from "svelte";
  import type { AutofocusState, FocuserState } from "../../lib/types";
  import FocuserNudge from "../devices/FocuserNudge.svelte";
  import ToolCard from "./ToolCard.svelte";

  let {
    focuser,
    autofocus,
    owner,
    locked,
    cameraBusy,
    open,
    ontoggle,
    onsheet,
    run,
    autofocusable = true,
    children,
  }: {
    focuser: FocuserState;
    autofocus: AutofocusState | null;
    owner: boolean;
    // Another job holds the focuser (a frame of the main camera).
    locked: boolean;
    // The main camera is busy: autofocus would be refused.
    cameraBusy: boolean;
    open: boolean;
    ontoggle: () => void;
    onsheet: () => void;
    run: (action: () => Promise<unknown>) => Promise<void>;
    autofocusable?: boolean;
    // Over the controls (Video's sharpness).
    children?: Snippet;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const running = $derived(autofocus?.state === "running");
  const steps = $derived(speedStep(capture.focusStep, capture.focusSpeed));
  const speedNames = $derived([t.live.focusSlow, t.live.focusNormal, t.live.focusFast]);
  const position = $derived(formatPlain(focuser.position, locale));
  const detail = $derived(
    focuser.target !== null
      ? t.focuser.moving(formatPlain(focuser.target, locale))
      : focuser.temperature !== null
        ? formatTemperature(focuser.temperature, locale)
        : "",
  );
</script>

<ToolCard
  icon="focus"
  title={t.focuser.title}
  {open}
  {ontoggle}
  tone={running || focuser.moving ? "accent" : null}
  toneText={running ? t.live.autofocusRunning : `${t.focuser.position} ${position}`}>
  {#snippet status()}
    <button type="button" class="position" onclick={onsheet}>
      <span class="mono">{position}</span>
      {#if detail}<span class="caption muted">{detail}</span>{/if}
    </button>
  {/snippet}
  {@render children?.()}
  <div class="speed">
    <span class="caption muted">{t.live.focusSpeed}</span>
    <PillSwitch
      label={t.live.focusSpeed}
      options={FOCUS_SPEEDS.map((speed, i) => ({ value: String(speed), label: speedNames[i] ?? String(speed) }))}
      value={String(capture.focusSpeed)}
      onchange={(value) => capture.setFocusSpeed(Number(value))} />
  </div>
  <FocuserNudge {focuser} step={steps} disabled={!owner || locked || running} {run} />
  {#if autofocusable}
  <div class="row">
    {#if running}
      <span class="caption" role="status">{t.live.autofocusRunning}</span>
    {:else}
      <Button disabled={!owner || locked || cameraBusy} onclick={() => void run(() => startAutofocus({}))}>
        {t.autofocus.open}
      </Button>
    {/if}
    <a class="link" href={href({ screen: "focus" })}>{t.live.autofocusCurve}</a>
  </div>
  {/if}
  {#if !owner}
    <p class="caption muted">{t.live.focusOwner}</p>
  {:else if locked}
    <p class="caption muted">{t.focuser.locked}</p>
  {:else if autofocusable && !running && cameraBusy}
    <p class="caption muted">{t.live.autofocusBusy}</p>
  {/if}
</ToolCard>

<style>
  .position {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    min-height: 36px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font-size: 17px;
    line-height: 20px;
    cursor: pointer;
  }
  .speed {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .link {
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }
</style>
