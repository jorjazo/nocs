#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  echo "usage: $0 <linux-arm64.tar.gz>" >&2
  exit 2
fi

if ! command -v qemu-aarch64-static >/dev/null 2>&1; then
  echo "SKIPPED: qemu-aarch64-static not installed; run 'sudo apt-get install -y qemu-user-static' first." >&2
  exit 0
fi

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && [ ! -e /proc/sys/fs/binfmt_misc/aarch64 ]; then
  echo "SKIPPED: aarch64 binfmt_misc not registered; on GitHub Actions use docker/setup-qemu-action@v3 first." >&2
  exit 0
fi

WORK=$(mktemp -d)
PID=""
trap 'if [ -n "${PID:-}" ]; then kill "$PID" 2>/dev/null || true; fi; rm -rf "$WORK"' EXIT

tar -C "$WORK" -xzf "$ARCHIVE"
DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d)

JAVA_BIN="$DIR/bin/java"
file "$JAVA_BIN" | grep -q 'ARM aarch64' || {
  echo "FAIL: $JAVA_BIN is not aarch64 ELF (this tarball was not built on linux-arm64)" >&2
  file "$JAVA_BIN" >&2
  exit 1
}

chmod +x "$DIR/bin/nocs" "$DIR/bin/java" 2>/dev/null || true
[ -f "$DIR/lib/jspawnhelper" ] && chmod +x "$DIR/lib/jspawnhelper" 2>/dev/null || true
[ -f "$DIR/lib/jexec" ] && chmod +x "$DIR/lib/jexec" 2>/dev/null || true

NOCS_DATA_DIR=$(mktemp -d) "$DIR/bin/nocs" > "$WORK/out.log" 2>&1 &
PID=$!

for i in $(seq 1 120); do
  if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
    echo "NOCS-arm64 is up under QEMU after ${i}s"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "launcher exited before serving HTTP; logs:" >&2
    cat "$WORK/out.log" >&2
    exit 1
  fi
  sleep 1
done

echo "NOCS-arm64 did not start within 120s under QEMU; logs:" >&2
cat "$WORK/out.log" >&2
exit 1
