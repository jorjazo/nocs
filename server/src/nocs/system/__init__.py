"""nocs-system, the privileged helper, and nocsd's client for it (ADR 0027).

nocs-system runs as root and performs a closed list of operations (reboot, host
name…) for nocsd, which reads everything else itself. Nothing in this package
imports the rest of ``nocs``, so the root process loads only the standard library
and anyio.
"""
