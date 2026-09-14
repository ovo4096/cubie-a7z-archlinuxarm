"""Focused package integration tests; run on Linux with Python 3.11+ and zstd."""
import contextlib
import gzip
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("package_bsp", Path(__file__).resolve().parents[2] / "tools/package_bsp.py")
bsp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bsp)


def module(name, release=bsp.KERNEL):
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    strings = b"\0.shstrtab\0.modinfo\0"
    metadata = f"vermagic={release} SMP mod_unload aarch64\0name={name}\0srcversion=FIXTURE\0".encode()
    body = strings + metadata
    sections = bytearray(64 * 3)
    struct.pack_into("<Q", header, 40, 64 + len(body))
    struct.pack_into("<HHH", header, 58, 64, 3, 1)
    struct.pack_into("<I", sections, 64, 1)
    struct.pack_into("<QQ", sections, 64 + 24, 64, len(strings))
    struct.pack_into("<I", sections, 128, 11)
    struct.pack_into("<QQ", sections, 128 + 24, 64 + len(strings), len(metadata))
    return bytes(header) + body + bytes(sections)


def make_fixture(root):
    info = root / "var/lib/dpkg/info"
    info.mkdir(parents=True)
    (root / "var/lib/dpkg/status").write_text("\n\n".join(f"Package: {name}\nVersion: {version}\nStatus: install ok installed\nArchitecture: arm64" for name, version in bsp.LOCKED.items()) + "\n")
    (root / "usr/lib").mkdir(parents=True)
    (root / "lib").symlink_to("usr/lib", target_is_directory=True)
    lists = {name: [] for name in bsp.LOCKED}

    def add(deb, name, data=b"test", target=None):
        path = bsp.vendor_path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if target is None:
            path.write_bytes(data)
        else:
            path.symlink_to(target)
        lists[deb].append("/" + name)

    image = bytearray(64)
    image[56:60] = b"ARMd"
    kernel_deb = f"linux-image-{bsp.KERNEL}"
    add(kernel_deb, f"boot/vmlinuz-{bsp.KERNEL}", bytes(image))
    add(kernel_deb, f"usr/lib/linux-image-{bsp.KERNEL}/allwinner/sun60i-a733-cubie-a7z.dtb")
    add(kernel_deb, f"lib/modules/{bsp.KERNEL}/kernel/test.ko.xz", lzma.compress(module("test")))
    add(kernel_deb, f"lib/modules/{bsp.KERNEL}/modules.builtin", b"builtin\n")
    add("aic8800-usb-dkms", f"lib/modules/{bsp.KERNEL}/updates/dkms/aic8800_fdrv_usb.ko.xz", lzma.compress(module("aic8800_fdrv")))
    add("img-bxm-dkms", f"lib/modules/{bsp.KERNEL}/updates/dkms/pvrsrvkm.ko.xz", lzma.compress(module("pvrsrvkm")))
    add("radxa-overlays-dkms", f"lib/modules/{bsp.KERNEL}/updates/dkms/radxa-overlays.ko.xz", lzma.compress(module("radxa_overlays")))
    add("radxa-overlays-dkms", "boot/dtbo/test.dtbo.disabled")
    add("u-boot-dlan17", "usr/lib/u-boot/radxa-cubie-a7s/u-boot-sunxi-with-spl.bin")
    add("u-boot-dlan17", "usr/lib/u-boot/radxa-cubie-a7s/setup.sh", b"#!/bin/sh\nexit 0\n")
    bsp.vendor_path(root, "usr/lib/u-boot/radxa-cubie-a7s/setup.sh").chmod(0o755)
    add("u-boot-dlan17", "usr/lib/u-boot/radxa-a733", target="radxa-cubie-a7s")
    add("radxa-firmware", "lib/firmware/board.bin")
    add("aic8800-firmware", "lib/firmware/aic.bin")
    for name in ("rgx.fw.36.56.104.183", "rgx.sh.36.56.104.183"):
        add("xserver-xorg-img-bxm-1.21.1-2.deb", "lib/firmware/" + name)
    add("radxa-system-config-aic8800-usb-dkms", "lib/modprobe.d/aic.conf", b"alias example aic_btusb_usb\n")
    for deb in lists:
        add(deb, f"usr/share/doc/{deb}/copyright", b"Fixture license\n")
    for deb, paths in lists.items():
        (info / (deb + ".list")).write_text("/./\n" + "\n".join(paths) + "\n")


@unittest.skipUnless(os.name == "posix" and shutil.which("zstd"), "Linux and zstd required")
class BspPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "vendor"
        make_fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def builder(self, output="output"):
        return bsp.Builder(self.root, self.base / output, 1700000000)

    def test_rootfs_absolute_symlinks_and_usrmerge(self):
        link = self.root / "usr/lib/firmware/link.bin"
        link.symlink_to("/lib/firmware/board.bin")
        self.assertEqual(bsp.vendor_path(self.root, "lib/firmware/link.bin", True), self.root / "usr/lib/firmware/board.bin")
        self.assertEqual(bsp.arch_path("/sbin/tool"), "usr/bin/tool")
        self.assertEqual(bsp.normalized_link("lib/firmware/link.bin", "usr/lib/firmware/link.bin", "/lib/firmware/board.bin"), "/usr/lib/firmware/board.bin")
        with self.assertRaisesRegex(ValueError, "Traversal"):
            bsp.vendor_path(self.root, "../../etc/passwd")

    def test_source_lock_rejects_version_drift(self):
        status = self.root / "var/lib/dpkg/status"
        status.write_text(status.read_text().replace("Version: 2026.04-3", "Version: 2026.04-4"))
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            self.builder()

    def test_module_abi_and_unclassified_modules_rejected(self):
        module_path = self.root / f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/aic8800_fdrv_usb.ko.xz"
        module_path.write_bytes(lzma.compress(module("aic8800_fdrv", "5.15.147-18-a733")))
        with self.assertRaisesRegex(ValueError, "ABI mismatch"):
            self.builder().select()
        module_path.write_bytes(lzma.compress(module("aic8800_fdrv")))
        extra = module_path.with_name("unexpected.ko.xz")
        extra.write_bytes(lzma.compress(module("unexpected")))
        with self.assertRaisesRegex(ValueError, "Unclassified external module"):
            self.builder().select()

    def test_wrong_kernel_format_rejected(self):
        (self.root / f"boot/vmlinuz-{bsp.KERNEL}").write_bytes(b"not ARM64")
        with self.assertRaisesRegex(ValueError, "not a raw ARM64 Image"):
            self.builder().select()

    def test_split_archives_metadata_and_reproducibility(self):
        with contextlib.redirect_stdout(io.StringIO()):
            first = self.builder("first").run()
            second = self.builder("second").run()
        self.assertEqual([p["sha256"] for p in first["packages"]], [p["sha256"] for p in second["packages"]])
        self.assertEqual(len(first["excluded_files"]), 2)
        owners = {}
        for package in first["packages"]:
            path = self.base / "first" / package["filename"]
            data = subprocess.check_output(["zstd", "-q", "-d", "-c", str(path)])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                names = archive.getnames()
                self.assertNotIn(".INSTALL", names)
                self.assertFalse(any(name.startswith("lib/") for name in names))
                info = archive.extractfile(".PKGINFO").read().decode()
                self.assertIn("arch = aarch64", info)
                mtree = gzip.decompress(archive.extractfile(".MTREE").read()).decode()
                self.assertIn("#mtree", mtree)
                self.assertIn("sha256digest=", mtree)
                for member in archive:
                    self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 1700000000))
                    if not member.isdir() and not member.name.startswith("."):
                        self.assertNotIn(member.name, owners)
                        owners[member.name] = package["name"]
                if package["name"] == "radxa-a7z-bootloader":
                    self.assertEqual(archive.getmember("usr/lib/u-boot/radxa-a733").linkname, "radxa-cubie-a7s")
                    self.assertEqual(archive.getmember("usr/lib/u-boot/radxa-cubie-a7s/setup.sh").mode, 0o755)
        self.assertEqual(owners[f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/pvrsrvkm.ko.xz"], "radxa-a7z-gpu-kmod")
        self.assertEqual(owners[f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/aic8800_fdrv_usb.ko.xz"], "radxa-a7z-wireless")
        self.assertNotIn("usr/lib/firmware/board.bin", owners)
        self.assertTrue((self.base / "first/SHA256SUMS.bsp").is_file())


if __name__ == "__main__":
    unittest.main()
