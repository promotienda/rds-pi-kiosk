#!/bin/bash -e
# Install the kiosk files, users and services into the image.

FILES=files/rootfs
while IFS= read -r -d '' f; do
	rel=${f#"$FILES"/}
	case "$rel" in
		usr/sbin/*|usr/lib/rds-pi-kiosk/mode-is|usr/lib/rds-pi-kiosk/session) mode=0755 ;;
		*) mode=0644 ;;
	esac
	install -D -o root -g root -m "$mode" "$f" "${ROOTFS_DIR}/$rel"
done < <(find "$FILES" -type f -print0)

install -D -o root -g root -m 0644 files/version "${ROOTFS_DIR}/etc/rds-pi-kiosk/version"
install -D -o root -g root -m 0644 files/README.md "${ROOTFS_DIR}/usr/share/doc/rds-pi-kiosk/README.md"
install -D -o root -g root -m 0644 files/LICENSE "${ROOTFS_DIR}/usr/share/doc/rds-pi-kiosk/LICENSE"

# kiosk.txt on the FAT partition, so it can be edited before the first boot.
install -m 0644 "${ROOTFS_DIR}/usr/share/rds-pi-kiosk/kiosk.txt.default" "${ROOTFS_DIR}/boot/firmware/kiosk.txt"

# A quiet, clean console: no blanking, no logo, no blinking cursor.
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
for opt in consoleblank=0 logo.nologo vt.global_cursor_default=0 quiet loglevel=3; do
	grep -qw -- "$opt" "$CMDLINE" || sed -i "1 s/\$/ $opt/" "$CMDLINE"
done

on_chroot << EOF2
set -e
id -u kiosk >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/rds-pi-kiosk/kiosk \
	--shell /usr/sbin/nologin --comment "RDS Pi Kiosk browser" kiosk
usermod -a -G video,render,input,audio kiosk
id -u kiosk-setup >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent \
	--shell /usr/sbin/nologin --comment "RDS Pi Kiosk setup page" kiosk-setup
install -d -o root -g root -m 0755 /var/lib/rds-pi-kiosk
install -d -o kiosk -g kiosk -m 0700 /var/lib/rds-pi-kiosk/kiosk
install -d -o kiosk-setup -g kiosk-setup -m 0750 /var/lib/rds-pi-kiosk/requests

systemctl enable rds-kiosk-config.service rds-kiosk.service rds-kiosk-setup.service rds-kiosk-request.path
# tty1 belongs to the kiosk. Other consoles keep a login prompt; no account
# has a usable password unless Raspberry Pi Imager or kiosk.txt sets one up.
systemctl disable getty@tty1.service
# The Raspberry Pi user-rename wizard takes over the screen (tty8) and waits
# for a keyboard. Accounts come from Raspberry Pi Imager (cloud-init) instead.
systemctl disable userconfig.service
systemctl set-default multi-user.target

# The admin user has no password: log in with Raspberry Pi Imager's settings
# (user, password, SSH) or SSH_AUTHORIZED_KEY in kiosk.txt.
passwd -l ${FIRST_USER_NAME}
rm -f /etc/sudoers.d/010_pi-nopasswd
EOF2
