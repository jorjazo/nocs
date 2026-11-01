<script lang="ts">
  // The focuser: where it is, in and out by a chosen step, go to a position,
  // stop. Opened from Live view and from Rig.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import SequenceHold from "../../components/SequenceHold.svelte";
  import Button from "../../components/Button.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import { moveFocuser } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { capture, FOCUS_STEPS, holder } from "../../lib/camera.svelte";
  import { errorText } from "../../lib/errors";
  import { formatPlain, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import FocuserNudge from "./FocuserNudge.svelte";

  let { onclose }: { onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const focuser = $derived(live.app.focuser ?? null);
  // A main camera exposure locks the focuser; its own moves show as moving.
  const lockedBy = $derived(holder(live.app.jobs, "focuser"));
  const locked = $derived(lockedBy !== null && lockedBy.info.kind !== "focus");
  const disabled = $derived(!auth.owner || locked);

  let target = $state<number | null>(untrack(() => live.app.focuser?.position ?? null));
  let busy = $state(false);
  let error = $state("");

  async function run(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = "";
    try {
      await action();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  // The focuser went away (disconnected): nothing left to control.
  $effect(() => {
    if (!focuser) onclose();
  });
</script>

<Sheet title={focuser?.device ?? t.focuser.title} {onclose}>
  {#if focuser}
    <div class="readouts">
      <div>
        <span class="label muted">{t.focuser.position}</span>
        <span class="readout">{formatPlain(focuser.position, locale)}</span>
        <span class="caption muted">
          {focuser.target !== null
            ? t.focuser.moving(formatPlain(focuser.target, locale))
            : focuser.max_position !== null
              ? t.focuser.max(formatPlain(focuser.max_position, locale))
              : ""}
        </span>
      </div>
      <div>
        <span class="label muted">{t.focuser.temperature}</span>
        <span class="readout">{focuser.temperature === null ? "—" : formatTemperature(focuser.temperature, locale)}</span>
      </div>
    </div>

    <div class="group">
      <span class="label muted">{t.focuser.step}</span>
      <SegmentedControl
        label={t.focuser.step}
        options={FOCUS_STEPS.map((step) => ({ value: String(step), label: formatPlain(step, locale) }))}
        value={String(capture.focusStep)}
        onchange={(value) => capture.setFocusStep(Number(value))} />
      <FocuserNudge {focuser} {disabled} {run} />
    </div>

    <div class="goto">
      <Stepper
        label={t.focuser.goTo}
        bind:value={target}
        min={0}
        max={focuser.max_position ?? 1_000_000}
        step={capture.focusStep}
        disabled={disabled || focuser.moving} />
      <Button
        wide
        {busy}
        disabled={disabled || focuser.moving || target === null || target === focuser.position}
        onclick={() => void run(() => moveFocuser({ position: target ?? 0 }))}>
        {t.focuser.go}
      </Button>
    </div>

    <Button wide onclick={() => router.go({ screen: "focus" })}>{t.autofocus.open}</Button>

    {#if locked && auth.owner}<p class="caption muted">{t.focuser.locked}</p>{/if}
    <SequenceHold resources={["focuser"]} />
    {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {/if}
</Sheet>

<style>
  .readouts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3);
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--raised);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .goto {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
