#!/bin/bash -e
# pi-gen: start this stage from the previous stage's root file system (stage2 = Lite).
if [ ! -d "${ROOTFS_DIR}" ]; then
	copy_previous
fi

# PRUNE_STAGES=1 (set by build.sh): the earlier stages' root file systems are
# only needed to re-run them, and they cost ~3 GB of disk. Never delete one
# that still has something mounted inside it.
if [ "${PRUNE_STAGES:-0}" = "1" ]; then
	for s in stage0 stage1 stage2; do
		d="${WORK_DIR}/${s}/rootfs"
		[ -d "$d" ] || continue
		if findmnt -rn -o TARGET | grep -q "^$(realpath "$d")"; then
			echo "prerun: $d has mounts, keeping it"
			continue
		fi
		rm -rf --one-file-system "$d"
		echo "prerun: pruned $d"
	done
fi
