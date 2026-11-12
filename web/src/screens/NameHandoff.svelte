<script lang="ts">
  // Takes this device to the box's new name with its pairing (ADR 0044): waits until
  // <name>.local answers, then opens the same screen there with the one-time token in
  // the URL's fragment. If it does not answer in time, a link opens it by hand.
  import Button from "../components/Button.svelte";
  import { handoffUrl, originFor, waitUntilAnswers } from "../lib/handoff";
  import { i18n } from "../lib/i18n";

  let {
    name,
    token,
    auto = true,
    wide = false,
  }: {
    // The box's new host name, without .local.
    name: string;
    token: string;
    // Start waiting at once; otherwise a button starts it (after instructions to read).
    auto?: boolean;
    wide?: boolean;
  } = $props();

  const t = $derived(i18n.t);
  const origin = $derived(originFor(name, location));
  const url = $derived(handoffUrl(origin, location.hash, token));

  let pressed = $state(false);
  let timedOut = $state(false);
  let seconds = $state(0);
  const waiting = $derived((auto || pressed) && !timedOut);

  $effect(() => {
    if (!waiting) return;
    const stop = new AbortController();
    const started = Date.now();
    seconds = 0;
    const tick = setInterval(() => (seconds = Math.round((Date.now() - started) / 1000)), 1000);
    const target = url;
    void waitUntilAnswers(origin, { signal: stop.signal }).then((answers) => {
      if (stop.signal.aborted) return;
      if (answers) location.replace(target);
      else timedOut = true;
    });
    return () => {
      stop.abort();
      clearInterval(tick);
    };
  });

  function wait(): void {
    timedOut = false;
    pressed = true;
  }
</script>

<div class="handoff">
  {#if waiting}
    <p role="status">{t.handoff.waiting(name, seconds)}</p>
  {:else if timedOut}
    <p role="status">{t.handoff.timeout(name)}</p>
    <div class="buttons">
      <a class="open" href={url}>{t.handoff.open(name)}</a>
      <Button variant="text" onclick={wait}>{t.handoff.retry}</Button>
    </div>
  {:else}
    <Button variant="primary" {wide} onclick={wait}>{t.handoff.go(name)}</Button>
  {/if}
</div>

<style>
  .handoff {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .buttons {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .open {
    display: inline-flex;
    align-items: center;
    min-height: var(--touch);
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
    overflow-wrap: anywhere;
  }
</style>
