<script lang="ts">
  // How to stop a sequence: after the frame in progress or now, running the end
  // (park, warm) or leaving the rig as it is.
  import Sheet from "../../components/Sheet.svelte";
  import { i18n } from "../../lib/i18n";

  let { onstop, onclose }: { onstop: (now: boolean, runEnd: boolean) => void; onclose: () => void } = $props();
  const t = $derived(i18n.t);
</script>

<Sheet title={t.session.stopTitle} {onclose}>
  <div class="choices">
    <button type="button" class="choice" onclick={() => onstop(false, true)}>
      <span class="name">{t.session.stopAfter}</span>
      <span class="muted small">{t.session.stopAfterHint}</span>
    </button>
    <button type="button" class="choice" onclick={() => onstop(true, true)}>
      <span class="name">{t.session.stopNow}</span>
      <span class="muted small">{t.session.stopNowHint}</span>
    </button>
    <button type="button" class="choice" onclick={() => onstop(false, false)}>
      <span class="name">{t.session.stopAfterBare}</span>
      <span class="muted small">{t.session.stopAfterBareHint}</span>
    </button>
    <button type="button" class="choice" onclick={() => onstop(true, false)}>
      <span class="name">{t.session.stopBare}</span>
      <span class="muted small">{t.session.stopBareHint}</span>
    </button>
  </div>
</Sheet>

<style>
  .choices {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .choice {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .name {
    font-weight: 600;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
</style>
