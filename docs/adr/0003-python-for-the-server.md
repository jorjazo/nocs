# 0003. Python for the server

Date: 2026-10-27 · Status: Accepted

## Context

The server combines device I/O, long-running workflows, a web API and image
analysis (debayering, stretching, star detection, curve fitting). It must run
well on a Raspberry Pi 5. The maintainer is fluent in several languages.

Options considered: Python, Go, Rust, Java.

## Decision

Python 3.12+ with asyncio for the core daemon. FastAPI (or Starlette) for HTTP
and WebSocket, Pydantic for schemas, numpy / sep / astropy for imaging.
Strict static typing (pyright or mypy in strict mode) and ruff are mandatory.
CPU-heavy image work runs in worker processes, not the event loop.

## Consequences

- Best scientific/astronomy ecosystem, fastest development.
- Performance-critical hotspots can later move to Rust extensions (PyO3)
  without changing the architecture.
- Packaging and memory use on the Pi need attention.
