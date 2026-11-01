<script lang="ts">
  // Plan's two halves: the target, and the sequence that images it.
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import { i18n } from "../../lib/i18n";
  import { router } from "../../lib/router.svelte";

  let { value }: { value: "target" | "sequence" } = $props();
  const t = $derived(i18n.t);
</script>

<SegmentedControl
  label={t.sequence.plan}
  options={[
    { value: "target", label: t.sequence.target },
    { value: "sequence", label: t.sequence.sequence },
  ]}
  {value}
  onchange={(next) => router.go(next === "sequence" ? { screen: "sequence" } : { screen: "plan" })} />
