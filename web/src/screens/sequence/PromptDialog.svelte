<script lang="ts">
  // The sequence waits for the user to ready the rig for another kind of frames
  // (cover the telescope, put the flat panel on, uncover it): asked on any screen,
  // with a vibration and a short tone where the device allows them. "Later" folds it
  // for this prompt; the Sequences view keeps asking in its dock.
  import Button from "../../components/Button.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import { resumeSequence, stopSequence } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { isActive } from "../../lib/sequence";
  import { prompting } from "./prompting.svelte";

  const t = $derived(i18n.t);
  const run = $derived(live.app.sequence?.run ?? null);
  const kind = $derived(isActive(run) && run.prompt ? run.prompt : null);
  // One prompt: this run, at this step.
  const key = $derived(kind && run ? `${run.run}:${run.current}:${kind}` : null);
  const shown = $derived(auth.owner && key !== null && prompting.dismissed !== key);

  let busy = $state<"ready" | "stop" | null>(null);
  let error = $state("");

  $effect(() => {
    if (key && auth.owner) alert();
  });

  function alert(): void {
    try {
      navigator.vibrate?.([200, 100, 200]);
    } catch {
      // Not on this device.
    }
    try {
      const audio = new AudioContext();
      const tone = audio.createOscillator();
      const gain = audio.createGain();
      tone.frequency.value = 660;
      gain.gain.setValueAtTime(0.15, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.6);
      tone.connect(gain).connect(audio.destination);
      tone.start();
      tone.stop(audio.currentTime + 0.6);
      tone.onended = () => void audio.close();
    } catch {
      // A page may not play sound before the user touches it.
    }
  }

  async function act(what: "ready" | "stop"): Promise<void> {
    busy = what;
    error = "";
    try {
      if (what === "ready") await resumeSequence();
      else await stopSequence({ run_end: true });
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = null;
    }
  }
</script>

{#if shown && kind}
  <Sheet title={t.sequence.prompt[kind].title} onclose={() => (prompting.dismissed = key)}>
    <p>{t.sequence.prompt[kind].body}</p>
    {#if error}<p class="error">{error}</p>{/if}
    {#snippet actions()}
      <Button variant="danger" busy={busy === "stop"} disabled={busy !== null} onclick={() => void act("stop")}>{t.sequence.prompt.stop}</Button>
      <Button variant="primary" busy={busy === "ready"} disabled={busy !== null} onclick={() => void act("ready")}>{t.sequence.prompt.ready}</Button>
    {/snippet}
  </Sheet>
{/if}

<style>
  p {
    margin: 0;
  }
  .error {
    margin-top: var(--space-2);
    color: var(--error);
  }
</style>
