<script lang="ts">
  // Rig → Optics and devices → Optical trains: the imaging and guiding trains
  // from the profile's optics and the cameras' sensors, with field and scale.
  import Section from "../../components/Section.svelte";
  import { formatDecimal } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import type { CameraState, Optics, Profile, Role, RoleState } from "../../lib/types";

  let { profile, devices }: { profile: Profile | null; devices: Partial<Record<Role, RoleState>> } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const cameras = $derived(live.app.cameras);

  function deviceName(device: RoleState | undefined): string | null {
    return device ? (device.device ?? device.driver) : null;
  }

  function train(optics: Optics | null | undefined, camera: CameraState | undefined, parts: (string | null)[]) {
    if (!optics) return null;
    const focal = optics.focal_length * (optics.reducer ?? 1);
    const ratio = optics.aperture ? focal / optics.aperture : null;
    const lens = `${formatDecimal(focal, locale, 0)} mm${ratio ? ` f/${formatDecimal(ratio, locale, 1)}` : ""}`;
    const sensor = camera?.sensor;
    const known = sensor && sensor.width > 0 && sensor.pixel_size > 0;
    const scale = known ? `${formatDecimal((206.265 * sensor.pixel_size) / focal, locale, 2)}″/px` : null;
    const fov = known
      ? [sensor.width, sensor.height]
          .map((px) => formatDecimal((((px * sensor.pixel_size) / 1000 / focal) * 180) / Math.PI, locale, 1) + "°")
          .join(" × ")
      : null;
    return { lens, chain: [lens, ...parts.filter((part) => part !== null)], scale, fov };
  }

  const imaging = $derived(
    train(profile?.imaging, cameras?.main_camera, [
      deviceName(devices.filter_wheel),
      deviceName(devices.focuser),
      deviceName(devices.main_camera),
    ]),
  );
  const guiding = $derived(
    train(
      profile?.guiding_through_imaging ? profile.imaging : profile?.guiding,
      cameras?.guide_camera,
      [deviceName(devices.guide_camera)],
    ),
  );
  const summary = $derived(imaging ? [imaging.lens, imaging.scale].filter(Boolean).join(" · ") : (guiding?.lens ?? null));
</script>

{#if imaging || guiding}
  <Section id="trains" title={t.rig.trains} {summary}>
    {#each [{ label: t.rig.imagingTrain, value: imaging }, { label: t.rig.guidingTrain, value: guiding }] as item (item.label)}
      {#if item.value}
        <div class="train">
          <div class="line">
            <h4 class="label muted">{item.label}</h4>
            <span class="mono muted">{[item.value.fov, item.value.scale].filter(Boolean).join(" · ")}</span>
          </div>
          <p class="chain">
            {#each item.value.chain as part, i (i)}
              {#if i > 0}<span class="arrow" aria-hidden="true">→</span>{/if}
              <span class:muted={i === 0}>{part}</span>
            {/each}
          </p>
        </div>
      {/if}
    {/each}
  </Section>
{/if}

<style>
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  h4 {
    margin: 0;
  }
  .train {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .train + .train {
    padding-top: var(--space-3);
    border-top: 1px solid var(--line);
  }
  .chain {
    display: flex;
    flex-wrap: wrap;
    column-gap: var(--space-2);
    margin: 0;
    font-size: 17px;
    line-height: 26px;
    overflow-wrap: anywhere;
  }
  .arrow {
    color: var(--muted);
  }
</style>
