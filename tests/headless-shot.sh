#!/bin/bash
# Screenshot the kiosk session (cage + Chromium) on wlroots' headless backend,
# inside the container started by tests/nspawn-boot.sh.
#
#   sudo tests/headless-shot.sh <workdir> <out.png> [wait-seconds]
#
# Installs grim into the TEST COPY (needs the internet) the first time.
set -euo pipefail
W=$1; OUT=$2; WAIT=${3:-25}
M() { systemd-run -M kiosktest --wait --pipe -q "$@"; }

M /bin/sh -c 'command -v grim >/dev/null || { apt-get update -q >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends grim >/dev/null; }'
M /bin/sh -c 'systemctl stop rds-kiosk.service cagetest.service 2>/dev/null; systemctl reset-failed cagetest.service 2>/dev/null; install -d -o kiosk -g kiosk -m 700 /run/kiosk-test; true'
M systemd-run --unit=cagetest --uid=kiosk --gid=kiosk \
	-E HOME=/var/lib/rds-pi-kiosk/kiosk -E XDG_RUNTIME_DIR=/run/kiosk-test \
	-E WLR_BACKENDS=headless -E WLR_RENDERER=pixman -E WLR_LIBINPUT_NO_DEVICES=1 \
	/usr/bin/cage -d -- /usr/lib/rds-pi-kiosk/session
sleep "$WAIT"
M runuser -u kiosk -- env XDG_RUNTIME_DIR=/run/kiosk-test WAYLAND_DISPLAY=wayland-0 grim /run/kiosk-test/shot.png
cp "$W/root/run/kiosk-test/shot.png" "$OUT" 2>/dev/null || machinectl copy-from kiosktest /run/kiosk-test/shot.png "$OUT"
echo "headless-shot: $OUT"
