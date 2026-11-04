<script lang="ts">
  // The name of a Wi-Fi network to join, chosen from those in range (ADR 0028). The
  // box scans once when the picker appears and again only when asked; "Other…" (or a
  // failed scan) leaves the name to be typed, as for a hidden network.
  import { untrack } from "svelte";
  import { scanNetworks } from "../lib/api";
  import { errorText } from "../lib/errors";
  import { i18n } from "../lib/i18n";
  import type { WifiNetwork } from "../lib/types";
  import Button from "./Button.svelte";
  import Icon from "./Icon.svelte";
  import TextField from "./TextField.svelte";

  let {
    label,
    value = $bindable(""),
    open = $bindable(false),
  }: {
    label: string;
    value?: string;
    // The chosen network has no password.
    open?: boolean;
  } = $props();

  const OTHER = "\u0000other";
  const t = $derived(i18n.t);
  let networks = $state<WifiNetwork[] | null>(null);
  let failed = $state("");
  let other = $state(false);

  async function scan(): Promise<void> {
    networks = null;
    failed = "";
    try {
      networks = await scanNetworks();
    } catch (e) {
      failed = errorText(e, t);
      networks = [];
    }
    if (networks.length === 0) other = true;
  }

  $effect(() => untrack(() => void scan()));

  // A network chosen before a new scan stays, in range or not.
  const shown = $derived.by((): WifiNetwork[] => {
    const list = networks ?? [];
    if (other || !value || list.some((n) => n.ssid === value)) return list;
    return [...list, { ssid: value, signal: 0, secured: !open }];
  });

  function pick(choice: string): void {
    other = choice === OTHER;
    value = other ? "" : choice;
    open = shown.find((n) => n.ssid === value)?.secured === false;
  }

  function text(network: WifiNetwork): string {
    const signal = network.signal > 0 ? ` · ${network.signal} %` : "";
    return `${network.ssid}${signal}${network.secured ? "" : ` · ${t.wifi.open}`}`;
  }
</script>

<div class="picker">
  <div class="row">
    <label class="select">
      <span class="label muted">{label}</span>
      <select bind:value={() => (other ? OTHER : value), pick}>
        <option value="" disabled>{networks === null ? t.wifi.scanning : t.wifi.choose}</option>
        {#each shown as network (network.ssid)}
          <option value={network.ssid}>{text(network)}</option>
        {/each}
        <option value={OTHER}>{t.wifi.other}</option>
      </select>
    </label>
    <Button label={t.wifi.rescan} busy={networks === null} onclick={() => void scan()}>
      <Icon name="loop" />
    </Button>
  </div>
  {#if failed}
    <p class="caption muted">{t.wifi.scanFailed(failed)}</p>
  {:else if networks?.length === 0}
    <p class="caption muted">{t.wifi.none}</p>
  {/if}
  {#if other}
    <TextField label={t.wifi.otherName} hint={t.wifi.otherHint} bind:value maxlength={32} />
  {/if}
</div>

<style>
  .picker {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .row {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
  }
  .select {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .select .label {
    font-size: 15px;
  }
  select {
    min-height: var(--primary-height);
    width: 100%;
    padding: 0 var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    font-size: 17px;
    text-overflow: ellipsis;
  }
</style>
