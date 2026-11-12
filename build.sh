#!/bin/bash
# Build the RDS Pi Kiosk image with pi-gen.
#
#   sudo ./build.sh                 # version from `git describe`
#   sudo VERSION=0.1.0 ./build.sh
#
# Needs a Debian/Ubuntu host (amd64 or arm64) with pi-gen's dependencies:
#   sudo apt install coreutils quilt parted qemu-user-binfmt debootstrap zerofree zip \
#     dosfstools e2fsprogs libcap2-bin libarchive-tools grep rsync xz-utils curl xxd \
#     file git kmod bc gpg pigz arch-test
# About 15 GB of free disk and 1-2 hours on 4 cores (amd64 hosts emulate arm64).
#
# Output in ./deploy/: rds-pi-kiosk-<version>-arm64.img.xz, its .sha256, and
# a .info with the package list.
set -euo pipefail

PI_GEN_REPO=https://github.com/RPi-Distro/pi-gen.git
PI_GEN_REF=2026-10-06-raspios-trixie-arm64          # pinned: a reproducible base
PI_GEN_COMMIT=b2cd98a9ee08a31ef7d0110ed09f2492bbd972ec
MIN_FREE_GB=${MIN_FREE_GB:-15}

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${WORK:-$HERE/work}
DEPLOY=${DEPLOY:-$HERE/deploy}
VERSION=${VERSION:-$(git -C "$HERE" describe --tags --always --dirty 2>/dev/null || echo dev)}
VERSION=${VERSION#v}

die() { echo "build.sh: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root (pi-gen needs chroot and loop devices)"
[[ "$VERSION" =~ ^[0-9A-Za-z.+~-]+$ ]] || die "bad VERSION: $VERSION"

mkdir -p "$WORK" "$DEPLOY"
free_gb=$(( $(df --output=avail -k "$WORK" | tail -n1) / 1024 / 1024 ))
[ "$free_gb" -ge "$MIN_FREE_GB" ] || die "only ${free_gb} GB free under $WORK; need ${MIN_FREE_GB} GB"

# pi-gen, at the pinned commit.
if [ ! -d "$WORK/pi-gen/.git" ]; then
	git clone --quiet --branch "$PI_GEN_REF" --depth 1 "$PI_GEN_REPO" "$WORK/pi-gen"
fi
have=$(git -C "$WORK/pi-gen" rev-parse HEAD)
[ "$have" = "$PI_GEN_COMMIT" ] || die "pi-gen is at $have, expected $PI_GEN_COMMIT ($PI_GEN_REF)"
# Only the kiosk image is exported, not the plain Lite image of stage2.
rm -f "$WORK/pi-gen/stage2/EXPORT_IMAGE"

# Our stage, plus the generated files it installs.
rm -rf "$WORK/pi-gen/stage-kiosk"
cp -a "$HERE/stage-kiosk" "$WORK/pi-gen/stage-kiosk"
F="$WORK/pi-gen/stage-kiosk/02-kiosk/files"
echo "$VERSION" > "$F/version"
cp "$HERE/README.md" "$F/README.md"
cp "$HERE/LICENSE" "$F/LICENSE"

# The admin account is created locked (00-run.sh); pi-gen still insists on a
# password when the first-boot rename wizard is off, so give it a throwaway.
FIRST_PASS=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
cat > "$WORK/pi-gen/config" <<CFG
IMG_NAME=rds-pi-kiosk-${VERSION}
PI_GEN_RELEASE="RDS Pi Kiosk ${VERSION}"
RELEASE=trixie
DEPLOY_COMPRESSION=xz
COMPRESSION_LEVEL=6
LOCALE_DEFAULT=en_US.UTF-8
KEYBOARD_KEYMAP=us
KEYBOARD_LAYOUT="English (US)"
TIMEZONE_DEFAULT=Etc/UTC
TARGET_HOSTNAME=rds-kiosk
FIRST_USER_NAME=kioskadmin
FIRST_USER_PASS=${FIRST_PASS}
DISABLE_FIRST_BOOT_USER_RENAME=1
ENABLE_SSH=0
ENABLE_CLOUD_INIT=1
WORK_DIR=${WORK}/pi-gen-work
DEPLOY_DIR=${DEPLOY}/pi-gen
STAGE_LIST="stage0 stage1 stage2 stage-kiosk"
CFG

cd "$WORK/pi-gen"
PRUNE_STAGES=1 CLEAN=1 setsid ./build.sh -c config &
PIGEN=$!

# Abort before the disk fills: the build host may be doing other work.
MIN_LEFT_GB=${MIN_LEFT_GB:-3}
( while kill -0 "$PIGEN" 2>/dev/null; do
	left=$(( $(df --output=avail -k "$WORK" | tail -n1) / 1024 / 1024 ))
	if [ "$left" -lt "$MIN_LEFT_GB" ]; then
		echo "build.sh: only ${left} GB left on the build disk; stopping pi-gen" >&2
		kill -TERM -- "-$PIGEN" 2>/dev/null || true
		exit 0
	fi
	sleep 20
  done ) &
WATCH=$!
rc=0; wait "$PIGEN" || rc=$?
kill "$WATCH" 2>/dev/null || true
[ "$rc" = 0 ] || die "pi-gen failed (exit $rc); see $WORK/pi-gen-work/build.log"

img=$(ls -t "$DEPLOY"/pi-gen/*-kiosk.img.xz | head -n1)
[ -f "$img" ] || die "pi-gen produced no image"
out="$DEPLOY/rds-pi-kiosk-${VERSION}-arm64.img.xz"
mv -f "$img" "$out"
info=$(ls -t "$DEPLOY"/pi-gen/*-kiosk.info 2>/dev/null | head -n1 || true)
[ -n "$info" ] && mv -f "$info" "${out%.img.xz}.info"
( cd "$DEPLOY" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" )
# The work tree is ~8 GB of root file systems; keep only the image.
if [ "${KEEP_WORK:-0}" != "1" ]; then
	if findmnt -rn -o TARGET | grep -q "^$(realpath "$WORK")/pi-gen-work"; then
		echo "build.sh: mounts left under $WORK/pi-gen-work; not deleting it" >&2
	else
		rm -rf --one-file-system "$WORK/pi-gen-work"
	fi
fi
echo "build.sh: OK $out"
echo "build.sh: $(stat -c %s "$out") bytes, sha256 $(cut -d' ' -f1 "$out.sha256")"
echo "build.sh: uncompressed $(xz --robot --list "$out" | awk '$1=="totals"{print $5}') bytes"
