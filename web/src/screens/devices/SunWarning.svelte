<script lang="ts">
  // The Sun's warning (ADR 0049): read and acknowledged once a day before NOCS points
  // near the Sun. Acknowledging it goes on with what was refused.
  import Banner from "../../components/Banner.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import { acknowledgeSun } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";

  let { onacknowledged, onclose }: { onacknowledged: () => void; onclose: () => void } = $props();

  const t = $derived(i18n.t);
  let busy = $state(false);
  let error = $state("");

  async function acknowledge(): Promise<void> {
    busy = true;
    error = "";
    try {
      await acknowledgeSun();
      onacknowledged();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

<Sheet title={t.sun.title} {onclose}>
  <Banner icon="alert" tone="error">{t.sun.blind}</Banner>
  <p>{t.sun.filter}</p>
  <p>{t.sun.others}</p>
  <p>{t.sun.nobody}</p>
  <p class="caption muted">{t.sun.lasts}</p>
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
  {#snippet actions()}
    <ConfirmButton
      label={t.sun.acknowledge}
      confirmLabel={t.sun.acknowledgeConfirm}
      {busy}
      onconfirm={() => void acknowledge()} />
  {/snippet}
</Sheet>

<style>
  p {
    margin: 0;
  }
</style>
