#!/usr/bin/env bash
# Run NOCS with ZWO EAF/EFW support. Requires libudev1 (apt install libudev1).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ZWO native libs need libudev (not linked); preload shipped lib or system
NATIVE_DIR="$SCRIPT_DIR/native/linux-x64"
export LD_PRELOAD="${LD_PRELOAD:-${NATIVE_DIR}/libudev.so.1}"
[[ -f "$LD_PRELOAD" ]] || export LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libudev.so.1"
export NOCS_EAF_SDK_PATH="${NOCS_EAF_SDK_PATH:-$NATIVE_DIR}"
export NOCS_EFW_SDK_PATH="${NOCS_EFW_SDK_PATH:-$NATIVE_DIR}"
export NOCS_ASI_SDK_PATH="${NOCS_ASI_SDK_PATH:-$NATIVE_DIR}"

if [[ -f build/libs/nocs-*.jar ]]; then
  exec java -jar build/libs/nocs-*.jar "$@"
else
  exec ./gradlew bootRun "$@"
fi
