#!/bin/sh
# Runs indiserver with a driver FIFO in a directory shared with the host
# (/run/indi), so nocsd outside the container can start and stop drivers.
# indiserver does not create the FIFO itself. The driver catalog is copied
# next to it for nocsd's driver list, and uploads/ is where camera drivers save
# frames for nocsd (UPLOAD_LOCAL). Starts as root only to prepare the
# directory (a bind mount owned by whoever created it), then drops privileges.
set -eu

run=/run/indi
mkdir -p "$run/drivers" "$run/uploads"
[ -p "$run/fifo" ] || mkfifo "$run/fifo"
cp /usr/share/indi/*.xml "$run/drivers/"
# Host users of any uid (CI runners are not 1000) must write the FIFO and be
# able to clean the directory up.
chmod 0777 "$run" "$run/drivers" "$run/uploads"
chmod 0666 "$run/fifo" "$run"/drivers/*.xml

exec setpriv --reuid=ubuntu --regid=ubuntu --init-groups indiserver -v -f "$run/fifo" "$@"
