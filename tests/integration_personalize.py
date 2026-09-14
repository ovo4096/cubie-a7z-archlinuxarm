#!/usr/bin/env python3
"""Real FAT/GPT personalization on new regular fixtures; no physical disks.

Fixtures contain only an ext4 identification superblock, not a bootable rootfs.
This exercise requires mtools/mkfs.fat, but requires no root or loop devices.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import image
import personalize as p


def fixture(work, sector):
    geometry = image.geometry(sector, 256)
    path = work / f"fixture-{sector}.img"
    size = geometry["disk_bytes"]
    count = size // sector
    entries = bytearray(128 * 128)
    for i, part in enumerate(geometry["partitions"]):
        entry = bytearray(128)
        entry[:16] = uuid.UUID(part["type"]).bytes_le
        entry[16:32] = uuid.uuid4().bytes_le
        struct.pack_into("<3Q", entry, 32, part["start"], part["start"] + part["size"] - 1, part["attributes"])
        name = part["name"].encode("utf-16-le")
        entry[56:56 + len(name)] = name
        entries[i * 128:(i + 1) * 128] = entry
    table_sectors = len(entries) // sector
    guid = uuid.uuid4().bytes_le
    def header(current, backup, table):
        raw = bytearray(sector)
        raw[:8] = b"EFI PART"
        struct.pack_into("<4I4Q", raw, 8, 0x10000, 92, 0, 0, current, backup, 2 + table_sectors, count - table_sectors - 2)
        raw[56:72] = guid
        struct.pack_into("<Q3I", raw, 72, table, 128, 128, zlib.crc32(entries) & 0xffffffff)
        struct.pack_into("<I", raw, 16, zlib.crc32(raw[:92]) & 0xffffffff)
        return raw
    fat = work / f"fixture-config-{sector}.fat"
    with fat.open("xb") as handle:
        handle.truncate(32768 * sector)
    # Force DOS track geometry: real image.py loop formatting can leave a
    # short unused tail, so do not test only an exactly full BPB volume.
    subprocess.run(["mkfs.fat", "-S", str(sector), "-g", "255/63", "-n", "config", str(fat)], check=True, stdout=subprocess.DEVNULL)
    metadata = {**geometry, "private_seed_included": False, "fixture_not_bootable": True}
    p.mtool("mcopy", fat, "-", "::/a7z-image.json", input=json.dumps(metadata).encode())
    with path.open("xb") as handle:
        handle.truncate(size)
        mbr = bytearray(512)
        mbr[450] = 0xee
        struct.pack_into("<II", mbr, 454, 1, min(count - 1, 0xffffffff))
        mbr[510:] = b"\x55\xaa"
        handle.write(mbr)
        handle.seek(sector); handle.write(header(1, count - 1, 2))
        handle.seek(2 * sector); handle.write(entries)
        handle.seek((count - table_sectors - 1) * sector); handle.write(entries)
        handle.seek((count - 1) * sector); handle.write(header(count - 1, 1, count - table_sectors - 1))
        handle.seek(32768 * sector); handle.write(fat.read_bytes())
        superblock = bytearray(1024)
        superblock[56:58] = b"\x53\xef"
        superblock[104:120] = uuid.uuid4().bytes
        handle.seek(geometry["partitions"][2]["start"] * sector + 1024); handle.write(superblock)
    expected = p.ufs.digest_file(path)
    Path(str(path) + ".sha256").write_text(f"{expected}  {path.name}\n")
    return path, expected


def exercise(work):
    results = []
    for sector in (512, 4096):
        original, checksum = fixture(work, sector)
        target = work / f"fixture-{sector}-private.img"
        args = SimpleNamespace(image=str(original), output=str(target), ssid="fixture;\u7f51\u7edc", hidden=True,
                               hostname="a7z-fixture", ssh_key=None, sha256=None)
        with contextlib.redirect_stdout(io.StringIO()) as messages:
            p.personalize(args, "test-passphrase")
        assert "test-passphrase" not in messages.getvalue()
        assert p.ufs.digest_file(original) == checksum
        with original.open("rb") as src, target.open("rb") as dst:
            layout = p.inspect(src)
            assert p.inspect(dst) == layout
            offset, end = layout["config_offset"], layout["config_offset"] + layout["config_bytes"]
            src.seek(0); dst.seek(0)
            position = 0
            while position < layout["disk_bytes"]:
                amount = min(8 * 1024 * 1024, layout["disk_bytes"] - position)
                old, new = src.read(amount), dst.read(amount)
                for start, stop in ((0, max(0, min(amount, offset - position))),
                                    (max(0, min(amount, end - position)), amount)):
                    assert old[start:stop] == new[start:stop]
                position += amount
            dst.seek(offset)
            extracted = work / f"private-config-{sector}.fat"
            extracted.write_bytes(dst.read(layout["config_bytes"]))
        profile = p.mtool("mcopy", extracted, "::/wifi/a7z-headless.nmconnection", "-")
        assert b"test-passphrase" not in profile and b"key-mgmt=wpa-psk" in profile
        assert p.mtool("mcopy", extracted, "::/hostname", "-") == b"a7z-fixture\n"
        assert json.loads(p.mtool("mcopy", extracted, "::/a7z-image.json", "-"))["private_seed_included"]
        assert json.loads(Path(str(target) + ".json").read_text())["private_seed_included"]
        again = SimpleNamespace(**vars(args)); again.image = str(target); again.output = str(work / f"again-{sector}-private.img")
        try:
            p.personalize(again, "test-passphrase")
            raise AssertionError("Already private source was accepted")
        except ValueError:
            pass
        assert not Path(again.output).exists()
        # Damage a GPT byte and validate before any attempt to modify FAT.
        damaged = work / f"bad-{sector}.img"
        with damaged.open("xb") as output, original.open("rb") as input:
            output.write(input.read(2 * sector))
        with damaged.open("rb") as handle:
            try:
                p.inspect(handle)
                raise AssertionError("Truncated GPT accepted")
            except ValueError:
                pass
        results.append({"sector_size": sector, "source_unchanged": True, "outside_config_unchanged": True,
                        "profile_roundtrip": True, "private_source_refused": True})
    print(json.dumps({"result": "PASS", "work": str(work), "checks": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    parent = Path(args.work_dir).resolve(strict=True)
    work = Path(tempfile.mkdtemp(prefix="personalize-integration-", dir=parent))
    exercise(work)
