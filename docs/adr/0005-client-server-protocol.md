# 0005. REST + WebSocket + HTTP client protocol

Date: 2026-10-27 · Status: Accepted

## Context

Clients need to send commands, receive live state from several devices and
long-running jobs, and fetch large binary data (previews, FITS). Connections
from phones over field Wi-Fi drop often. Remote access is a long-term goal.

Alternatives considered: SSE + REST (limited to 6 connections per host on
plain HTTP/1.1), WebTransport (requires TLS, uneven browser support),
gRPC-Web (no bidirectional streaming in browsers), MQTT (needs a broker and
still runs over WebSocket in browsers), WebRTC (overkill on LAN, interesting
for remote access).

## Decision

- REST/JSON for commands and configuration; long operations return a job id.
- One WebSocket per client for state and events: initial versioned snapshot,
  then sequenced patches; resume from the last version on reconnect.
- Plain HTTP for binary resources, announced over the WebSocket.
- Schemas defined once in Pydantic, exported to JSON Schema / OpenAPI, and
  TypeScript types generated from them.

## Consequences

- Robust reconnection and multi-client consistency by design.
- Binary data stays cacheable and out of the state channel.
- The transport can be swapped (e.g. WebRTC via relay) without redesigning
  the protocol.
