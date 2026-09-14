#!/usr/bin/env python3
"""Linux root-only integration checks, restricted to new temp image files and loops.

Uses an explicitly fake U-Boot payload: output images are fixtures, not bootable.
No physical disk is passed to a formatting, partitioning or write command.
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


installer = load("installer", REPO / "runtime/a7z-install-ufs")
grower = load("grower", REPO / "runtime/a7z-grow-root")


def run(*args, capture=False):
    result = subprocess.run([str(arg) for arg in args], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def exercise(work):
    root = work / "source"
    for relative in ("boot/extlinux", "etc/kernel", "usr/lib/u-boot/radxa-a733"):
        (root / relative).mkdir(parents=True)
    (root / "boot/extlinux/extlinux.conf").write_text("default primary\nlabel primary\n  linux /boot/Image\n  fdt /boot/dtb/allwinner/sun60i-a733-cubie-a7z.dtb\n  append root=UUID=@ROOT_UUID@ console=ttyS0 ro\n")
    (root / "etc/kernel/cmdline").write_text("root=UUID=@ROOT_UUID@ console=ttyS0 ro\n")
    (root / "etc/fstab").write_text("# test image\nUUID=OLD / ext4 defaults 0 1\n")
    sentinel = os.urandom(128 * 1024)
    (root / "sentinel").write_bytes(sentinel)
    boot = root / "usr/lib/u-boot/radxa-a733"
    (boot / "u-boot-sunxi-with-spl.bin").write_bytes(b"TEST ONLY - NOT A BOOTLOADER\n" * 200)
    (boot / "setup.sh").write_text('''#!/bin/bash
set -euo pipefail
test "$1" = update_bootloader
offset=256
if test "$3" = 4096; then offset=2064; fi
dd if="$(dirname "$0")/u-boot-sunxi-with-spl.bin" of="$2" bs=512 seek="$offset" conv=notrunc,fsync
''')
    seed = work / "seed"
    seed.mkdir()
    (seed / "test-seed.txt").write_text("config seed payload\n")
    uuids = []
    for sector in (512, 4096):
        output = work / f"fixture-{sector}.img"
        run("python3", REPO / "tools/image.py", "build", "--rootfs", root, "--output", output,
            "--sector-size", sector, "--root-size-mib", 256, "--config-dir", seed)
        manifest = json.loads(Path(str(output) + ".json").read_text())
        uuids.append(manifest["filesystem_uuids"]["rootfs"])
        if sector == 4096:
            inspected = installer.inspect_image(output)
            assert inspected["root_uuid"] == uuids[-1]
        loop = run("losetup", "--find", "--show", "--partscan", "--sector-size", sector, output, capture=True)
        assert loop.startswith("/dev/loop")
        mounted = []
        try:
            mount = work / f"mount-{sector}"
            mount.mkdir()
            run("mount", "-o", "ro", f"{loop}p3", mount)
            mounted.append(mount)
            for relative in ("etc/kernel/cmdline", "boot/extlinux/extlinux.conf", "etc/fstab"):
                assert uuids[-1] in (mount / relative).read_text()
                assert "@ROOT_UUID@" not in (mount / relative).read_text()
            assert (mount / "sentinel").read_bytes() == sentinel
            run("mount", "-o", "ro", f"{loop}p1", mount / "config")
            mounted.append(mount / "config")
            assert (mount / "config/test-seed.txt").read_text() == "config seed payload\n"
        finally:
            for mountpoint in reversed(mounted):
                run("umount", mountpoint)
            run("losetup", "--detach", loop)
    assert len(set(uuids)) == 2
    # Exercise both write/read-back/relocate branches on separate new loop disks.
    # Only hardware discovery is substituted; there is no production CLI bypass.
    for grow_root in (False, True):
        target_file = work / f"installer-target-grow-{grow_root}.img"
        with target_file.open("xb") as handle:
            handle.truncate(4 * 1024**3)
        target_loop = run("losetup", "--find", "--show", "--partscan", "--sector-size", 4096, target_file, capture=True)
        original_inspect = installer.inspect_target
        original_reread = installer.reread_partition_table
        reread_fds = []
        def inspect_test_target(target, image_bytes):
            assert target == Path(target_loop)
            assert Path((Path("/sys/class/block") / target.name / "loop/backing_file").read_text().strip()).resolve() == target_file
            info = target.stat()
            assert int(run("blockdev", "--getsize64", target, capture=True)) == 4 * 1024**3
            return {"target": str(target), "bytes": 4 * 1024**3, "sector_size": 4096,
                    "major_minor": f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}",
                    "controller": "test-file-backed-loop", "lun": 0}
        def reread_test_target(destination):
            assert not destination.closed
            descriptor = destination.fileno()
            assert os.fstat(descriptor).st_rdev == Path(target_loop).stat().st_rdev
            reread_fds.append(descriptor)
            return original_reread(destination)
        try:
            installer.inspect_target = inspect_test_target
            installer.reread_partition_table = reread_test_target
            installer.install(SimpleNamespace(image=str(work / "fixture-4096.img"), target=target_loop,
                                              sha256=None, grow_root=grow_root, dry_run=False, confirm=target_loop))
            assert len(reread_fds) == (2 if grow_root else 1)
            assert len(set(reread_fds)) == 1
            actual_root_bytes = int(run("blockdev", "--getsize64", f"{target_loop}p3", capture=True))
            assert actual_root_bytes > 3 * 1024**3 if grow_root else actual_root_bytes == 256 * 1024**2
            check_mount = work / f"installed-root-grow-{grow_root}"
            check_mount.mkdir()
            run("mount", "-o", "ro", f"{target_loop}p3", check_mount)
            try:
                assert (check_mount / "sentinel").read_bytes() == sentinel
            finally:
                run("umount", check_mount)
        finally:
            installer.inspect_target = original_inspect
            installer.reread_partition_table = original_reread
            run("losetup", "--detach", target_loop)
    # Mimic writing a smaller 4 KiB-sector image onto a larger disk, without physical disks.
    image = work / "fixture-4096.img"
    with image.open("r+b") as handle:
        handle.truncate(4 * 1024**3)
    loop = run("losetup", "--find", "--show", "--partscan", "--sector-size", 4096, image, capture=True)
    mount = work / "grow-mount"
    mount.mkdir()
    try:
        run("mount", f"{loop}p3", mount)
        try:
            plan = grower.plan_for_root(str(mount), allow_test_loop=True)
            assert plan["growth_bytes"] > 3 * 1024**3
            backup = grower.apply_plan(plan, work / "gpt-backups")
            assert (backup / "table.sfdisk").is_file()
            assert (mount / "sentinel").read_bytes() == sentinel
            again = grower.plan_for_root(str(mount), allow_test_loop=True)
            assert again["growth_bytes"] == 0
            assert again["root_filesystem_uuid"] == uuids[-1]
            assert again["old_backup_lba"] == again["new_backup_lba"]
            # Rerunning is harmless and repairs a previously completed partition-only operation.
            grower.apply_plan(again, work / "gpt-backups")
        finally:
            run("umount", mount)
        run("e2fsck", "-f", "-n", f"{loop}p3")
    finally:
        run("losetup", "--detach", loop)
    print(json.dumps({"result": "PASS", "work": str(work), "distinct_root_uuids": uuids,
                      "checks": ["512/4096 actual GPT/filesystems", "U-Boot offset bytes",
                                 "fstab/cmdline/extlinux UUIDs", "config seed", "installer full write/read-back with and without grow",
                                 "BLKRRPART via the still-owned fd in both installer branches",
                                 "mounted ext4 online growth",
                                 "GPT relocation", "start/UUID/content preserved", "idempotent rerun", "e2fsck"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, help="parent for a fresh image-test directory")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("requires root for temporary loop mounts")
    parent = Path(args.work_dir).resolve(strict=True)
    # Keep artifacts and logs for review; never clean an arbitrary caller-supplied tree.
    work = Path(tempfile.mkdtemp(prefix="image-integration-", dir=parent))
    exercise(work)


if __name__ == "__main__":
    main()
