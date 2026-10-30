<script lang="ts">
  // A destructive action that needs a second tap within a few seconds. No
  // browser dialog: it would flash white in Night mode.
  import Button from "./Button.svelte";

  let {
    label,
    confirmLabel,
    busy = false,
    onconfirm,
  }: { label: string; confirmLabel: string; busy?: boolean; onconfirm: () => void } = $props();

  let armed = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  function press(): void {
    clearTimeout(timer);
    if (armed) {
      armed = false;
      onconfirm();
      return;
    }
    armed = true;
    timer = setTimeout(() => (armed = false), 4000);
  }

  $effect(() => () => clearTimeout(timer));
</script>

<span aria-live="polite">
  <Button variant={armed ? "danger" : "secondary"} {busy} onclick={press}>
    {armed ? confirmLabel : label}
  </Button>
</span>
