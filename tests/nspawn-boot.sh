#!/bin/bash
# Boot a COPY of a built image in a systemd-nspawn container on an arm64
# Debian host (no Pi needed) and leave it running for checks.
#
#   sudo tests/nspawn-boot.sh up   <image.img.xz> <workdir>
#   sudo tests/nspawn-boot.sh down <workdir>
#
# The copy gets test-only changes (the image itself is never modified):
#  - units that would touch hardware or the host's network are masked
#    (NetworkManager, ModemManager, cloud-init, rpi-resize, ...); the container
#    shares the host's network, so the setup page answers on the host's :80;
#  - Chromium gets --no-sandbox --disable-gpu (no user namespaces or GPU here);
#  - an optional kiosk.txt replaces the default ($KIOSK_TXT).
# What cannot be tested here: cage on tty1/DRM, HDMI, touch, Wi-Fi. Use
# tests/headless-shot.sh for the browser and a real Pi for the rest.
set -euo pipefail

cmd=${1:-}
case "$cmd" in
up)
	IMG=$2; W=$(realpath -m "$3")
	mkdir -p "$W/root"
	if [ ! -f "$W/test.img" ]; then
		case "$IMG" in
			*.xz) xz -dc "$IMG" > "$W/test.img" ;;
			*) cp --sparse=always "$IMG" "$W/test.img" ;;
		esac
	fi
	LOOP=$(losetup -fP --show "$W/test.img")
	echo "$LOOP" > "$W/loop"
	mount "${LOOP}p2" "$W/root"
	mount "${LOOP}p1" "$W/root/boot/firmware"
	R="$W/root"
	for u in NetworkManager NetworkManager-wait-online ModemManager wpa_supplicant \
	         cloud-init-local cloud-init-main cloud-init-network cloud-config cloud-final cloud-init \
	         rpi-resize rpi-resize-swap-file systemd-timesyncd avahi-daemon ssh \
	         bluetooth hciuart triggerhappy dphys-swapfile rpi-eeprom-update \
	         systemd-binfmt; do
		ln -sf /dev/null "$R/etc/systemd/system/$u.service"
	done
	mkdir -p "$R/etc/chromium.d"
	echo 'export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-sandbox --disable-gpu"' > "$R/etc/chromium.d/99-nspawn-test"
	if [ -n "${KIOSK_TXT:-}" ]; then cp "$KIOSK_TXT" "$R/boot/firmware/kiosk.txt"; fi
	systemd-run --unit=kiosktest --collect -p KillMode=mixed \
		systemd-nspawn --quiet --keep-unit --boot --machine=kiosktest \
		--resolv-conf=copy-host --timezone=off -D "$R"
	for _ in $(seq 60); do
		if systemd-run -M kiosktest --wait --pipe -q /bin/true 2>/dev/null; then break; fi
		sleep 2
	done
	systemd-run -M kiosktest --wait --pipe -q systemctl is-system-running --wait || true
	echo "nspawn-boot: up; run commands with: systemd-run -M kiosktest --wait --pipe -q <cmd>"
	;;
down)
	W=$(realpath -m "$2")
	machinectl terminate kiosktest 2>/dev/null || true
	sleep 3
	umount -R "$W/root" 2>/dev/null || true
	[ -f "$W/loop" ] && losetup -d "$(cat "$W/loop")" 2>/dev/null || true
	rm -f "$W/loop"
	echo "nspawn-boot: down (the test copy $W/test.img is kept; delete it when done)"
	;;
*)
	echo "usage: $0 up <image> <workdir> | down <workdir>" >&2; exit 2 ;;
esac
