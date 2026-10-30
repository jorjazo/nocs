#!/usr/bin/env bash
# Phase 0 performance measurements: run on the Raspberry Pi 5 (or any machine for
# a baseline). See docs/spikes/pi5-performance.md for setup.
#
#   SAMPLES  where frames are written and read: put it on the storage you want to
#            measure (microSD vs USB SSD)            default: <results>/samples
#   ASTAP    ASTAP command-line solver               default: astap_cli
#   ASTAP_DB star database directory                 default: /opt/astap
#   SKIP     space-separated steps to skip: build samples preview astap guide
set -euo pipefail

# uv's installer puts it in ~/.local/bin, which non-login shells (ssh host cmd) lack.
export PATH="$HOME/.local/bin:$PATH"
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${OUT:-$ROOT/dev/bench/results/$(hostname)-$(date +%Y%m%d-%H%M)}
SAMPLES=${SAMPLES:-$OUT/samples}
ASTAP=${ASTAP:-astap_cli}
ASTAP_DB=${ASTAP_DB:-/opt/astap}
SKIP=${SKIP:-}
COMPOSE=(docker compose -f "$ROOT/dev/compose.yaml")

mkdir -p "$OUT" "$SAMPLES"
cd "$ROOT"
skip() { [[ " $SKIP " == *" $1 "* ]]; }
step() { echo; echo "== $*"; }

thermals() {
    # vcgencmd needs access to /dev/vcio, which is root-only on Ubuntu.
    local vc=(vcgencmd)
    vcgencmd get_throttled >/dev/null 2>&1 || vc=(sudo -n vcgencmd)
    if "${vc[@]}" get_throttled >/dev/null 2>&1; then
        echo "$("${vc[@]}" measure_temp) $("${vc[@]}" get_throttled)"
    else
        echo "vcgencmd not available"
    fi
}

step "system information -> $OUT/system.txt"
{
    echo "date: $(date -Is)"
    uname -a
    grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
    grep -m1 -E 'Model|model name' /proc/cpuinfo || true
    echo "cpus: $(nproc)"
    free -m
    echo "samples storage:"; df -h "$SAMPLES"; findmnt -T "$SAMPLES" -o SOURCE,FSTYPE,TARGET
    echo "thermals (start): $(thermals)"
    docker --version; uv --version
} | tee "$OUT/system.txt"

if ! skip build; then
    step "build and start INDI simulators and PHD2 (first build takes a while)"
    start=$(date +%s)
    "${COMPOSE[@]}" up -d --build
    echo "compose up: $(( $(date +%s) - start )) s" | tee -a "$OUT/system.txt"
fi
timeout 120 bash -c 'until (echo > /dev/tcp/127.0.0.1/7624) 2>/dev/null; do sleep 1; done'

if ! skip samples; then
    step "create sample frames -> $SAMPLES"
    uv run --project server python dev/bench/make_samples.py --out "$SAMPLES" | tee "$OUT/samples.log"
fi

if ! skip preview; then
    step "preview pipeline and star metrics"
    uv run dev/bench/preview_bench.py "$SAMPLES" --json "$OUT/preview.json" | tee "$OUT/preview.log"
fi

if ! skip astap; then
    step "ASTAP plate solving"
    if command -v "$ASTAP" >/dev/null || [[ -x "$ASTAP" ]]; then
        python3 dev/bench/astap_bench.py "$SAMPLES" --astap "$ASTAP" --db "$ASTAP_DB" \
            --json "$OUT/astap.json" | tee "$OUT/astap.log"
    else
        echo "skipped: $ASTAP not found (set ASTAP and ASTAP_DB)" | tee "$OUT/astap.log"
    fi
fi

if ! skip guide; then
    step "PHD2 guiding on the simulators, sampling resources every 5 s"
    echo "time,container,cpu,mem,loadavg,temp_c" > "$OUT/resources.csv"
    (
        while true; do
            load=$(cut -d' ' -f1 /proc/loadavg)
            temp=$(awk '{printf "%.1f", $1 / 1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "")
            docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' |
                sed "s|^|$(date +%T),|; s|$|,$load,$temp|" >> "$OUT/resources.csv"
            sleep 5
        done
    ) &
    sampler=$!
    trap 'kill $sampler 2>/dev/null || true' EXIT
    uv run --project server python dev/spikes/phd2_probe.py guide | tee "$OUT/guide.log"
    kill $sampler
fi

echo "thermals (end): $(thermals)" | tee -a "$OUT/system.txt"
step "summary"
python3 dev/bench/summarize.py "$OUT" | tee "$OUT/summary.md"
echo
echo "Results in $OUT (samples are large; they are not needed to share results)."
