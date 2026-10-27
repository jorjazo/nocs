# NOCS — New Observatory Controls System

NOCS is an open, web-first control system for amateur astrophotography rigs.
It runs on a small Linux computer at the telescope (Raspberry Pi 5, mini PC or
any Linux box), drives the equipment through [INDI](https://indilib.org), and is
operated from any phone, tablet or computer through the browser.

The goal: the ease of use of a dedicated appliance, without the vendor lock-in.

> **Status:** design phase. Nothing usable yet.

## Key ideas

- **The server runs the night.** Sequences, guiding and safety live on the
  telescope computer. Clients can disconnect at any time without affecting the
  session.
- **Any device is a client.** A single Progressive Web App for phones, tablets
  and desktops. No app stores.
- **Built on open standards.** INDI for devices, PHD2 for guiding, ASTAP for
  plate solving, FITS for data.
- **Guided workflows first.** Polar alignment, focusing, framing and sequencing
  as simple, opinionated flows with advanced settings within reach.

## Documentation

- [Product and architecture design](docs/design.md)
- [Architecture decision records](docs/adr/)
- [Roadmap](docs/roadmap.md)

## License

NOCS is licensed under the [GNU Affero General Public License v3.0](LICENSE).
Contributions are accepted under the [Developer Certificate of Origin](CONTRIBUTING.md).
