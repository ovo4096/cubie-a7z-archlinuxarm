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
from unittest import mock

SPEC = importlib.util.spec_from_file_location("package_bsp", Path(__file__).resolve().parents[2] / "tools/package_bsp.py")
bsp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bsp)


def module(name, release=bsp.KERNEL, version=None, srcversion="FIXTURE", flags="SMP mod_unload aarch64"):
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    strings = b"\0.shstrtab\0.modinfo\0"
    metadata = f"vermagic={release} {flags}\0name={name}\0srcversion={srcversion}\0".encode()
    if version is not None:
        metadata += f"version={version}\0".encode()
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
    add("img-bxm-dkms", f"lib/modules/{bsp.KERNEL}/updates/dkms/pvrsrvkm.ko.xz",
        lzma.compress(module("pvrsrvkm"), format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32,
                      filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20, "preset": 6}]))
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
        self.gpu_path = f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/pvrsrvkm.ko.xz"
        self.fixed_elf = module("pvrsrvkm", srcversion="FIXTURE-FIXED")
        self.compiler_patch = mock.patch.object(bsp, "build_fixed_module", side_effect=self.compiler_result)
        self.compiler = self.compiler_patch.start()
        self.addCleanup(self.compiler_patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def builder(self, output="output"):
        return bsp.Builder(self.root, self.base / output, 1700000000)

    def compiler_result(self, vendor_root, source_date_epoch, jobs=2):
        self.assertEqual((vendor_root, source_date_epoch, jobs), (self.root, 1700000000, 2))
        original = (self.root / self.gpu_path).read_bytes()
        return self.fixed_elf, {"schema": 1, "fix": "generic-drm-fdinfo",
                                "source_date_epoch": source_date_epoch, "original_module_path": self.gpu_path,
                                "module_sha256": bsp.sha256(self.fixed_elf),
                                "original_module_sha256": bsp.sha256(original),
                                "original_elf_sha256": bsp.sha256(lzma.decompress(original)),
                                "vermagic": bsp.elf_modinfo(self.fixed_elf)["vermagic"],
                                "patch": {"path": "gpu/kernel/0001-use-generic-drm-fdinfo.patch",
                                          "sha256": "0" * 64}}

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

    def test_gpu_payload_is_replaced_and_provenance_binds_both_binaries(self):
        original = (self.root / self.gpu_path).read_bytes()
        builder = self.builder()
        builder.select()
        self.compiler.assert_called_once_with(self.root, 1700000000, jobs=2)
        entry = builder.entries["radxa-a7z-gpu-kmod"][self.gpu_path]
        self.assertNotIn("source", entry)
        self.assertEqual(lzma.decompress(entry["data"]), self.fixed_elf)
        self.assertNotEqual(entry["data"], original)
        self.assertEqual((self.root / self.gpu_path).read_bytes(), original)
        self.assertEqual(entry["source_sha256"], bsp.sha256(original))
        self.assertEqual(entry["sha256"], entry["fixed_sha256"])
        self.assertEqual(entry["fixed_elf_sha256"], bsp.sha256(self.fixed_elf))
        provenance = builder.provenance("radxa-a7z-gpu-kmod")
        installed = json.loads(builder.entries["radxa-a7z-gpu-kmod"][bsp.GPU_FIX_PROVENANCE]["data"])
        self.assertEqual(provenance["module_rebuild"], installed)
        self.assertEqual(installed["source_elf_sha256"], bsp.sha256(lzma.decompress(original)))
        self.assertEqual(installed["fixed_sha256"], bsp.sha256(entry["data"]))
        self.assertEqual(provenance["modules"][0]["srcversion"], "FIXTURE-FIXED")
        self.assertTrue(provenance["modules"][0]["rebuilt"])
        self.assertEqual(bsp.SPECS["radxa-a7z-gpu-kmod"]["version"], "0.1.0_3-3")
        self.assertFalse(builder.output.exists(), "No compiler workspace should be left in package output")

    @unittest.skipUnless(shutil.which("xz"), "xz required for independent stream/filter inspection")
    def test_gpu_xz_matches_t5_crc32_and_one_mib_dictionary(self):
        builder = self.builder()
        builder.select()
        payload = builder.entries["radxa-a7z-gpu-kmod"][self.gpu_path]["data"]
        decoder = lzma.LZMADecompressor(memlimit=2 << 20)
        self.assertEqual(decoder.decompress(payload), self.fixed_elf)
        self.assertTrue(decoder.eof)
        self.assertEqual(decoder.unused_data, b"")
        self.assertEqual(decoder.check, lzma.CHECK_CRC32)
        self.assertEqual(builder.gpu_module_rebuild["compression"],
                         "xz, CRC32, LZMA2 dict=1MiB, preset 6")

        # xz independently inspects the on-disk filter properties, including
        # the dictionary size, for both the vendor fixture and actual result.
        rebuilt = self.base / "rebuilt.ko.xz"
        rebuilt.write_bytes(payload)
        for path in (self.root / self.gpu_path, rebuilt):
            with self.subTest(path=path.name):
                rows = [line.split("\t") for line in subprocess.check_output(
                    ["xz", "--robot", "--list", "--verbose", "--verbose", str(path)],
                    text=True).splitlines()]
                file_row = next(row for row in rows if row[0] == "file")
                self.assertEqual(file_row[1:3], ["1", "1"])
                self.assertEqual(file_row[6], "CRC32")
                self.assertEqual([row[-1] for row in rows if row[0] == "block"],
                                 ["--lzma2=dict=1MiB"])

        # A host round-trip alone accepted the broken CRC64/8MiB format.
        # Keep that counterexample so this check cannot regress to round-trip
        # validation without testing the kernel-compatible stream parameters.
        incompatible = lzma.compress(self.fixed_elf, check=lzma.CHECK_CRC64, preset=6)
        self.assertEqual(lzma.decompress(incompatible), self.fixed_elf)
        old_decoder = lzma.LZMADecompressor()
        old_decoder.decompress(incompatible)
        self.assertEqual(old_decoder.check, lzma.CHECK_CRC64)
        with self.assertRaises(lzma.LZMAError):
            lzma.decompress(incompatible, memlimit=2 << 20)

    def test_rebuilt_gpu_wrong_name_version_and_vermagic_rejected(self):
        for fixed in (module("not_pvrsrvkm"), module("pvrsrvkm", version="different"),
                      module("pvrsrvkm", release="6.6.99-4-aw2511"),
                      module("pvrsrvkm", flags="SMP mod_unload modversions aarch64")):
            with self.subTest(modinfo=bsp.elf_modinfo(fixed)):
                self.fixed_elf = fixed
                with self.assertRaisesRegex(ValueError, "ABI mismatch"):
                    self.builder().select()
                self.assertFalse(self.builder().output.exists())

    def test_multiple_pvrsrvkm_entries_are_not_packaged(self):
        duplicate = (self.root / self.gpu_path).with_name("pvr_duplicate.ko.xz")
        duplicate.write_bytes(lzma.compress(module("pvrsrvkm")))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.builder().select()
        self.compiler.assert_not_called()

    def test_gpu_compiler_failure_noop_or_unbound_provenance_never_falls_back(self):
        builder = self.builder()
        self.compiler.side_effect = RuntimeError("fixture compiler failed")
        with self.assertRaisesRegex(RuntimeError, "compiler failed"):
            builder.run()
        self.assertFalse(builder.output.exists())
        with self.assertRaisesRegex(ValueError, "without the validated"):
            builder.archive("radxa-a7z-gpu-kmod")
        self.compiler.side_effect = self.compiler_result
        self.fixed_elf = module("pvrsrvkm")
        with self.assertRaisesRegex(ValueError, "changed ELF"):
            self.builder().select()
        self.fixed_elf = module("pvrsrvkm", srcversion="FIXTURE-FIXED")
        fixed, report = self.compiler_result(self.root, 1700000000)
        for key in ("module_sha256", "original_module_sha256", "original_elf_sha256", "vermagic", "fix",
                    "source_date_epoch", "original_module_path"):
            with self.subTest(key=key):
                self.compiler.side_effect = None
                self.compiler.return_value = fixed, {**report, key: "incorrect"}
                with self.assertRaisesRegex(ValueError, "provenance"):
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
                if package["name"] == "radxa-a7z-gpu-kmod":
                    self.assertIn("pkgver = 0.1.0_3-3", info)
                    payload = archive.extractfile(self.gpu_path).read()
                    self.assertEqual(lzma.decompress(payload), self.fixed_elf)
                    self.assertEqual(payload[7], lzma.CHECK_CRC32)
                    fixed_report = json.loads(archive.extractfile(bsp.GPU_FIX_PROVENANCE).read())
                    package_report = json.loads(archive.extractfile("usr/share/doc/radxa-a7z-gpu-kmod/bsp-provenance.json").read())
                    self.assertEqual(fixed_report["fixed_sha256"], bsp.sha256(payload))
                    self.assertEqual(package_report["module_rebuild"], fixed_report)
        self.assertEqual(owners[f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/pvrsrvkm.ko.xz"], "radxa-a7z-gpu-kmod")
        self.assertEqual(owners[f"usr/lib/modules/{bsp.KERNEL}/updates/dkms/aic8800_fdrv_usb.ko.xz"], "radxa-a7z-wireless")
        self.assertNotIn("usr/lib/firmware/board.bin", owners)
        self.assertTrue((self.base / "first/SHA256SUMS.bsp").is_file())


if __name__ == "__main__":
    unittest.main()
