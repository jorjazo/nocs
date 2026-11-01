# Architecture Decision Records

Each ADR records one significant decision: its context, the decision, and its
consequences. ADRs are immutable once accepted; a change of mind is a new ADR
that supersedes the old one.

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-indi-as-device-backplane.md) | INDI as the device backplane | Accepted |
| [0003](0003-python-for-the-server.md) | Python for the server | Accepted |
| [0004](0004-web-pwa-client.md) | Single web PWA client (Svelte + TypeScript) | Accepted |
| [0005](0005-client-server-protocol.md) | REST + WebSocket + HTTP client protocol | Accepted |
| [0006](0006-reuse-phd2-and-astap.md) | Reuse PHD2 for guiding and ASTAP for plate solving | Accepted |
| [0007](0007-ubuntu-lts-base-os.md) | Ubuntu Server LTS as the base OS | Accepted |
| [0008](0008-agpl-license-and-dco.md) | AGPL-3.0 license and DCO | Accepted |
| [0009](0009-monorepo-and-english.md) | Monorepo, English for code and docs | Accepted |
| [0010](0010-privileged-system-helper.md) | Separate privileged system helper | Accepted |
| [0011](0011-equipment-profiles-and-driver-management.md) | Equipment profiles and indiserver driver management | Accepted |
| [0012](0012-image-pipeline.md) | Image transfer and preview pipeline | Accepted |
| [0013](0013-storage-and-catalog.md) | Storage destinations, file layout and frame catalog | Accepted |
| [0014](0014-authentication-and-pairing.md) | Authentication and device pairing | Accepted |
| [0015](0015-mount-control-and-client-time.md) | Mount control: slew pad dead man's switch and client time | Accepted |
| [0016](0016-settings-per-physical-device.md) | Settings per physical device: filter names by serial number | Accepted |
| [0017](0017-roles-by-capability-power-and-weather.md) | Roles by capability: power and weather, and what each output feeds | Accepted |
| [0018](0018-plate-solving-with-astap.md) | Plate solving with ASTAP | Proposed |
| [0019](0019-bundled-catalogs-and-their-licences.md) | Bundled catalogs and their licences | Proposed |
| [0020](0020-framing-chart.md) | Framing chart and its star data (Tycho-2, CC BY-NC 3.0 IGO) | Proposed |
| [0021](0021-autofocus.md) | Autofocus: V-curve sweep with a hyperbolic fit | Proposed |
| [0022](0022-phd2-as-a-managed-service.md) | PHD2 as a service configured by nocsd | Proposed |
| [0023](0023-guide-camera-and-mount-shared-with-phd2.md) | Guide camera and mount shared with PHD2 | Proposed |
| [0024](0024-dithering-between-frames.md) | Dithering and settling between frames | Proposed |
| [0025](0025-packaging-and-updates.md) | Packaging, apt repository and updates | Proposed |
| [0026](0026-raspberry-pi-image.md) | Raspberry Pi image | Proposed |
| [0027](0027-nocs-system.md) | nocs-system: what the privileged helper does, and what nocsd does itself | Proposed |
| [0028](0028-networking.md) | Appliance networking: access point, station, fallback, names and firewall | Proposed |
| [0029](0029-system-time-and-site.md) | System time and site from NTP, a GPS or the client | Proposed |
| [0030](0030-supervision.md) | Supervision of indiserver, drivers, PHD2 and nocsd | Proposed |
| [0031](0031-sequences.md) | Sequences: model, persistence and who owns the devices | Proposed |
| [0032](0032-sequence-recovery-and-restarts.md) | Sequences: recovery, safety and restarts | Proposed |
| [0033](0033-meridian-flip.md) | Sequences: the meridian flip | Proposed |
| [0034](0034-polar-alignment.md) | Polar alignment from three solved frames | Proposed |
| [0035](0035-apt-repository-and-release-publishing.md) | Apt repository, signing and release publishing | Proposed |

Template: Context → Decision → Consequences.
