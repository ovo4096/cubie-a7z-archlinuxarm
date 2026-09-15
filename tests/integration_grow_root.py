#!/usr/bin/env python3
"""Root-only regression on fresh sparse image-backed loops, never physical disks.

Exercise 512/4096 sectors, direct imaging and prior sgdisk -e repair, mounted
ext4 growth, metadata/content preservation and an idempotent retry. Artifacts
remain in a unique directory for inspection; cleanup never recursively deletes.
"""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("grow_root_regression", str(REPO / "runtime/a7z-grow-root"))
spec = importlib.util.spec_from_loader(loader.name, loader)
grower = importlib.util.module_from_spec(spec)
loader.exec_module(grower)


def run(*args, input=None):
    result = subprocess.run(list(map(str, args)), input=input, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def attach(image, sector):
    loop = run("losetup", "--find", "--show", "--partscan", "--sector-size", sector, image)
    require(re.fullmatch(r"/dev/loop[0-9]+", loop), "Only loop fixtures may be written")
    mapping = json.loads(run("losetup", "--json", "--output", "NAME,BACK-FILE,LOG-SEC", loop))["loopdevices"]
    require(len(mapping) == 1 and Path(mapping[0]["back-file"]).resolve() == image.resolve()
            and int(mapping[0]["log-sec"]) == sector, "Wrong backing image or sector size")
    return loop


def exercise(work, sector, repaired):
    directory = work / f"sector-{sector}-sgdisk-{int(repaired)}"
    directory.mkdir()
    image = directory / "fixture.img"
    with image.open("xb") as stream:
        stream.truncate(1 << 30)
    starts = [32768, 65536, 679936] if sector == 512 else [32768, 65536, 142336]
    sizes = [starts[1] - starts[0], starts[2] - starts[1], (256 << 20) // sector]
    loop = attach(image, sector)
    try:
        table = "label: gpt\nunit: sectors\n" + "\n".join(
            f"start={start},size={size},type={kind},name={name}"
            for start, size, kind, name in zip(starts, sizes, ("L", "U", "L"), ("config", "efi", "rootfs"))) + "\n"
        run("sfdisk", loop, input=table)
        run("mkfs.ext4", "-F", "-q", "-O", "^orphan_file,^metadata_csum_seed", "-E", "lazy_itable_init=0,lazy_journal_init=0", loop + "p3")
    finally:
        run("losetup", "--detach", loop)
    with image.open("r+b") as stream:
        stream.truncate(4 << 30)
    loop = attach(image, sector)
    mount = directory / "root"
    mount.mkdir()
    mounted = False
    try:
        if repaired:
            run("sgdisk", "-e", loop)
        before = grower.read_table(Path(loop))
        run("mount", loop + "p3", mount)
        mounted = True
        sentinel = b"A7Z synthetic growth regression\n" * 2048
        (mount / "sentinel").write_bytes(sentinel)
        plan = grower.plan_for_root(str(mount), allow_test_loop=True)
        require(plan["growth_bytes"] > 3 << 30, "Expected substantial root growth")
        if repaired:
            require(plan["old_backup_lba"] == plan["new_backup_lba"], "sgdisk did not relocate backup")
            require(plan["last_usable_lba"] == before["lastlba"] < plan["physical_last_usable_lba"], "Fixture did not preserve a GPT tail gap")
        backup = grower.apply_plan(plan, directory / "backups")
        after = grower.plan_for_root(str(mount), allow_test_loop=True)
        require(after["growth_bytes"] == 0, "Root did not reach declared usable boundary")
        require(after["root_filesystem_uuid"] == plan["root_filesystem_uuid"], "Filesystem UUID changed")
        require((mount / "sentinel").read_bytes() == sentinel, "Filesystem content changed")
        effective = json.loads((backup / "effective-plan.json").read_text())
        grower.assert_preserved(before, after["original_table"], loop + "p3", effective["new_size_sectors"])
        require(after["start_lba"] + after["old_size_sectors"] - 1 == after["current_last_usable_lba"], "Root crossed or missed GPT usable boundary")
        grower.apply_plan(after, directory / "backups")
        require(grower.plan_for_root(str(mount), allow_test_loop=True)["growth_bytes"] == 0, "Retry is not idempotent")
        run("umount", mount)
        mounted = False
        run("e2fsck", "-f", "-n", loop + "p3")
        result = {"sector_size": sector, "prior_sgdisk_repair": repaired, "result": "PASS",
                  "root_size_bytes": after["old_size_sectors"] * sector,
                  "reserved_tail_gap_sectors": after["physical_last_usable_lba"] - after["current_last_usable_lba"],
                  "sentinel_sha256": hashlib.sha256(sentinel).hexdigest()}
        print(json.dumps(result), flush=True)
        return result
    finally:
        # Unmount failure deliberately prevents detachment; keep artifacts.
        if mounted:
            run("umount", mount)
        run("losetup", "--detach", loop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    require(os.geteuid() == 0, "Requires Linux root for file-backed loop fixtures")
    parent = args.work_dir.resolve(strict=True)
    work = Path(tempfile.mkdtemp(prefix="grow-root-regression-", dir=parent))
    results = [exercise(work, sector, repaired) for sector in (512, 4096) for repaired in (False, True)]
    (work / "report.json").write_text(json.dumps({"results": results}, indent=2) + "\n")
    print(json.dumps({"result": "PASS", "cases": len(results), "work": str(work)}), flush=True)


if __name__ == "__main__":
    main()
