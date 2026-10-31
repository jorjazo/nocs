#!/bin/sh
# Start a virtual display and run PHD2 on it. (xvfb-run is unreliable as PID 1.)
#
# PHD2_SETTINGS names the settings file that nocsd writes (ADR 0022). It is
# imported with `phd2 -l` when PHD2 starts, so nocsd applies a new one by asking
# PHD2 to shut down and letting the supervisor (container restart policy,
# systemd) start it again. Until nocsd has written it, PHD2_SETTINGS_DEFAULT is
# imported instead, if set. PHD2_DISPLAY picks the X display (default 99).
set -eu
display="${PHD2_DISPLAY:-99}"
# A display killed with its lock and socket left behind (the previous run of
# this container or unit) would refuse to start again.
rm -f "/tmp/.X${display}-lock" "/tmp/.X11-unix/X${display}"
# PHD2's single-instance lock holds a PID. After a crash or a power cut that PID
# may belong to another process (this very script, in a container), and PHD2 then
# waits forever on an invisible "already running" dialog. This service is the
# only PHD2 there is.
rm -f "$HOME/phd2.1"
Xvfb ":${display}" -screen 0 1280x1024x24 -nolisten tcp &
export DISPLAY=":${display}"
for _ in $(seq 50); do
    [ -e "/tmp/.X11-unix/X${display}" ] && break
    sleep 0.1
done
# Importing replaces every PHD2 profile, calibration included: import only a
# file that differs from the one imported last.
settings="${PHD2_SETTINGS:-}"
if [ -z "$settings" ] || [ ! -f "$settings" ]; then
    settings="${PHD2_SETTINGS_DEFAULT:-}"
fi
imported="$HOME/.nocs-phd2-imported"
if [ -n "$settings" ] && [ -f "$settings" ] && ! cmp -s "$settings" "$imported"; then
    phd2 -l "$settings"
    cp "$settings" "$imported"
fi
exec phd2 "$@"
