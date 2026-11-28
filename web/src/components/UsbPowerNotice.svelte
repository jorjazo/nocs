<script lang="ts">
  // What connecting found on the Raspberry Pi's limited USB ports, if anything.
  import { usbPowerText } from "../lib/camerafault";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import Banner from "./Banner.svelte";

  const power = $derived(live.app.equipment?.usb_power ?? null);
</script>

{#if power}
  <Banner icon="power" tone="warning">{usbPowerText(power, i18n.t, i18n.locale)}</Banner>
{/if}
