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
- [UX and design system](docs/ux.md)
- [Architecture decision records](docs/adr/)
- [Roadmap](docs/roadmap.md)

## Development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 24 and pnpm.

```sh
# INDI simulators with a real star catalog (localhost:7624) and headless PHD2
# configured for them (JSON-RPC on localhost:4400)
docker compose -f dev/compose.yaml up -d

# Server: tests (unit + integration against the simulators), lint, types
cd server
uv sync
NOCS_TEST_INDI=localhost:7624 uv run pytest
uv run ruff check . && uv run pyright

# Web client, built and served by nocsd at http://127.0.0.1:8000
cd ../web
pnpm install && pnpm build
cd .. && NOCS_WEB_DIR=web/dist uv run --project server nocsd
```

After changing wire or state models in `server/src/nocs/api/schemas.py`, run
`pnpm gen:types` in `web/` to regenerate the TypeScript types (CI checks they
are up to date).

For live-reloading UI work, run `pnpm dev` in `web/` while nocsd runs; Vite
proxies `/api` to it. nocsd is configured with `NOCS_*` environment variables
(see `server/src/nocs/config.py`). It has no authentication yet and listens on
127.0.0.1 by default.

## License

NOCS is licensed under the [GNU Affero General Public License v3.0](LICENSE).
Contributions are accepted under the [Developer Certificate of Origin](CONTRIBUTING.md).
