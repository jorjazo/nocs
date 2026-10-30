#!/bin/sh
# Start a virtual display and run PHD2 on it. (xvfb-run is unreliable as PID 1.)
set -eu
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
export DISPLAY=:99
for _ in $(seq 50); do
    [ -e /tmp/.X11-unix/X99 ] && break
    sleep 0.1
done
# Optionally import a settings file (profiles) before starting, as `phd2 -l` does.
if [ -n "${PHD2_SETTINGS:-}" ]; then
    phd2 -l "$PHD2_SETTINGS"
fi
exec phd2 "$@"
