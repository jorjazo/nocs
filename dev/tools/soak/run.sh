#!/usr/bin/env bash
# A soak test: a long simulated night on its own simulators and nocsd (see soak.py).
# Runs on a PC or the lab Pi without touching their other stacks: compose project
# nocs-soak, INDI on 27624, PHD2 on 24400, nocsd on 127.0.0.1:28000, config and data
# in the results directory, no nocs-system. Then it writes summary.md.
#
#   HOURS     length of the night                      default: 1
#   EXPOSURE  light frames, seconds                    default: 5
#   ASTAP     ASTAP command-line solver (centring)     default: dev/.astap/astap_cli
#   ASTAP_DB  its star database                        default: next to ASTAP
#   OUT       results directory                        default: dev/tools/soak/results/<host>-<date>
#   KEEP      frame files kept on disk                 default: 60
#   ARGS      more options for soak.py run
#   DOWN      1: stop the simulators afterwards        default: 1
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HERE="$ROOT/dev/tools/soak"
OUT=${OUT:-$HERE/results/$(hostname)-$(date +%Y%m%d-%H%M)}
HOURS=${HOURS:-1}
EXPOSURE=${EXPOSURE:-5}
ASTAP=${ASTAP:-$ROOT/dev/.astap/astap_cli}
ASTAP_DB=${ASTAP_DB:-$(dirname "$ASTAP")}
KEEP=${KEEP:-60}
DOWN=${DOWN:-1}
mkdir -p "$OUT/run" "$OUT/config" "$OUT/data"
OUT=$(cd "$OUT" && pwd)
export SOAK_RUN="$OUT/run" SOAK_INDI_PORT=27624 SOAK_PHD2_PORT=24400
COMPOSE=(docker compose -p nocs-soak -f "$HERE/compose.yaml")
{
    echo "date: $(date -Is)"
    uname -a
    grep -E '^PRETTY_NAME=' /etc/os-release || true
    grep -m1 -E 'Model|model name' /proc/cpuinfo || true
    echo "cpus: $(nproc)"
    free -m
    df -h "$OUT"
    echo "commit: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "hours: $HOURS exposure: $EXPOSURE keep: $KEEP"
} > "$OUT/system.txt"

"${COMPOSE[@]}" up -d --build
timeout 120 bash -c "until (echo > /dev/tcp/127.0.0.1/$SOAK_INDI_PORT) 2>/dev/null; do sleep 1; done"
timeout 120 bash -c "until (echo > /dev/tcp/127.0.0.1/$SOAK_PHD2_PORT) 2>/dev/null; do sleep 1; done"

(cd "$ROOT/server" && uv sync --quiet)
env NOCS_HOST=127.0.0.1 NOCS_PORT=28000 \
    NOCS_CONFIG_DIR="$OUT/config" NOCS_DATA_DIR="$OUT/data" \
    NOCS_INDI_HOST=127.0.0.1 NOCS_INDI_PORT=$SOAK_INDI_PORT \
    NOCS_INDI_FIFO="$SOAK_RUN/fifo" NOCS_INDI_DRIVERS_DIR="$SOAK_RUN/drivers" \
    NOCS_INDI_UPLOAD_DIR=/run/indi/uploads NOCS_INDI_UPLOAD_DIR_LOCAL="$SOAK_RUN/uploads" \
    NOCS_PHD2_HOST=127.0.0.1 NOCS_PHD2_PORT=$SOAK_PHD2_PORT NOCS_PHD2_SETTINGS="$SOAK_RUN/phd2.phd" \
    NOCS_PHD2_INDI_HOST=indi NOCS_PHD2_INDI_PORT=7624 \
    NOCS_ASTAP="$ASTAP" NOCS_ASTAP_DB="$ASTAP_DB" \
    NOCS_SYSTEM_SOCKET="$OUT/run/no-nocs-system" NOCS_GPSD_PORT=1 \
    "$ROOT/server/.venv/bin/nocsd" > >(cat > "$OUT/nocsd.log") 2>&1 &
# Through a pipe, as into journald under systemd: written straight to a file on the
# microSD, a log line waits for the card while it takes a frame (ext4 data=ordered),
# and with it nocsd's event loop (up to 1.9 s on the lab Pi).
NOCSD=$!
cleanup() {
    kill "$NOCSD" 2>/dev/null && wait "$NOCSD" 2>/dev/null || true
    "${COMPOSE[@]}" logs --no-color --timestamps > "$OUT/containers.log" 2>&1 || true
    if [ "$DOWN" = 1 ]; then "${COMPOSE[@]}" down; fi
}
trap cleanup EXIT
timeout 60 bash -c 'until curl -sf http://127.0.0.1:28000/api/health >/dev/null; do sleep 1; done'

status=0
"$ROOT/server/.venv/bin/python" "$HERE/soak.py" run --url http://127.0.0.1:28000 \
    --nocsd-pid "$NOCSD" --containers nocs-soak-indi-1,nocs-soak-phd2-1 \
    --out "$OUT" --storage "$OUT/data" --hours "$HOURS" --exposure "$EXPOSURE" \
    --keep-frames "$KEEP" ${ARGS:-} || status=$?
"$ROOT/server/.venv/bin/python" "$HERE/soak.py" summarize "$OUT" > /dev/null || true
echo "results: $OUT (status $status)"
exit $status
