"""Safety/unit tests; no block devices are opened or modified by this suite."""
import copy
import errno
import hashlib
import io
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import struct
import unittest
import zlib
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


builder = load("a7z_image", REPO / "tools/image.py")
installer = load("a7z_installer", REPO / "runtime/a7z-install-ufs")
grower = load("a7z_grower", REPO / "runtime/a7z-grow-root")


class ImageGeometryTests(unittest.TestCase):
    def test_official_t5_logical_sector_layouts(self):
        sd = builder.geometry(512, 1024)
        ufs = builder.geometry(4096, 1024)
        self.assertEqual([p["start"] * 512 for p in sd["partitions"]], [16 << 20, 32 << 20, 332 << 20])
        self.assertEqual([p["start"] * 4096 for p in ufs["partitions"]], [128 << 20, 256 << 20, 556 << 20])
        self.assertEqual(sd["partitions"][1]["size"] * 512, 300 << 20)
        self.assertEqual(ufs["partitions"][1]["size"] * 4096, 300 << 20)

    def test_root_rewrite_covers_fallback_entries_preserves_arisc_path(self):
        source = "default primary\nlabel primary\n  fdt /boot/dtb/a7z.dtb\n  APPEND console=ttyS0 root=UUID=old ro\nlabel fallback\n append root=/dev/sda3 root=PARTUUID=bad rootwait quiet\n"
        changed = builder.rewrite_extlinux(source, "unique-new-uuid")
        self.assertEqual(changed.count("root=UUID=unique-new-uuid"), 2)
        self.assertEqual(changed.count("rootwait"), 2)
        self.assertIn("fdt /boot/dtb/a7z.dtb", changed)
        self.assertNotIn("root=/dev/sda3", changed)
        self.assertNotIn("root=PARTUUID=bad", changed)

    def test_invalid_boot_configuration_refused(self):
        with self.assertRaises(ValueError):
            builder.rewrite_extlinux("label kernel\nlinux /Image\n", "uuid")

    def test_fstab_only_replaces_image_partitions(self):
        changed = builder.rewrite_fstab("# root\n/dev/sda3 / ext4 defaults 0 1\nUUID=data /data ext4 defaults 0 2\n", dict(rootfs="new", config="c", efi="e"))
        self.assertNotIn("/dev/sda3", changed)
        self.assertIn("UUID=data /data", changed)


class InstallerRefusalTests(unittest.TestCase):
    def setUp(self):
        self.disk = {"name": "/dev/sda", "type": "disk", "size": 128 << 30,
                     "log-sec": 4096, "maj:min": "8:0", "ro": False,
                     "mountpoints": [None], "children": [
                         {"name": "/dev/sda3", "type": "part", "maj:min": "8:3", "mountpoints": [None]}]}

    def check(self, disk=None, controller="ufshcd", mounted=None, swap=None, holders=None, size=10 << 30):
        installer.validate_target(disk or self.disk, size, controller, mounted or set(), swap or set(), holders or {})

    def test_unused_ufs_data_disk_accepted(self):
        self.check()

    def test_four_mib_boot_lun_refused(self):
        self.disk["size"] = 4 << 20
        with self.assertRaisesRegex(ValueError, "small UFS LUN"):
            self.check(size=1 << 20)

    def test_current_root_and_other_mounts_refused(self):
        with self.assertRaisesRegex(ValueError, "mounted"):
            self.check(mounted={"8:3"})
        self.disk["children"][0]["mountpoints"] = ["/"]
        with self.assertRaisesRegex(ValueError, "mounted"):
            self.check()

    def test_active_swap_and_holders_refused(self):
        with self.assertRaisesRegex(ValueError, "swap"):
            self.check(swap={"8:3"})
        with self.assertRaisesRegex(ValueError, "holder"):
            self.check(holders={"sda3": ["dm-0"]})

    def test_wrong_bus_readonly_partition_sector_and_size_refused(self):
        with self.assertRaisesRegex(ValueError, "ufshcd"):
            self.check(controller="usb-storage")
        for key, value in (("ro", True), ("type", "part"), ("log-sec", 512), ("size", 8 << 30)):
            disk = copy.deepcopy(self.disk)
            disk[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(disk=disk)

    def test_compressed_or_arbitrary_file_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.img"
            path.write_bytes(bytes(4096))
            with self.assertRaisesRegex(ValueError, "protective MBR"):
                installer.inspect_image(path)

    def test_checksum_filename_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.img"
            Path(str(path) + ".sha256").write_text("a" * 64 + "  unrelated.img\n")
            with self.assertRaisesRegex(ValueError, "filename"):
                installer.expected_digest(path, None)


class GrowRootSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("/dev/sda3")
        self.table = {"label": "gpt", "unit": "sectors", "sectorsize": 4096,
                      "id": "disk-uuid", "partitions": [
                          {"node": "/dev/sda1", "start": 32768, "size": 32768, "type": installer.LINUX_TYPE, "uuid": "one"},
                          {"node": "/dev/sda2", "start": 65536, "size": 76800, "type": installer.EFI_TYPE, "uuid": "two"},
                          {"node": "/dev/sda3", "start": 142336, "size": 65536, "type": installer.LINUX_TYPE, "uuid": "three", "attrs": "LegacyBIOSBootable"}]}

    def test_nonfinal_root_refused(self):
        with self.assertRaisesRegex(ValueError, "final"):
            grower.validate_layout(self.table, Path("/dev/sda1"), 4 << 30, 4096, 1048570)

    def test_overlap_and_shrink_refused(self):
        self.table["partitions"][2]["start"] = 140000
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            grower.validate_layout(self.table, self.root, 4 << 30, 4096, 1048570)
        self.table["partitions"][2]["start"] = 142336
        with self.assertRaisesRegex(ValueError, "out-of-bounds"):
            grower.validate_layout(self.table, self.root, 4 << 30, 4096, 160000)

    def test_start_or_uuid_changes_detected(self):
        for key, value in (("start", 150000), ("uuid", "replacement"), ("attrs", None)):
            after = copy.deepcopy(self.table)
            after["partitions"][2][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "identity"):
                grower.assert_preserved(self.table, after, str(self.root), 65536)

    def gpt_fixture(self, directory, sector, backup_lba, last_usable):
        path = Path(directory) / "gpt.img"
        entries = bytes(128 * 128)
        header = bytearray(sector)
        header[:8] = b"EFI PART"
        struct.pack_into("<III", header, 8, 0x10000, 92, 0)
        struct.pack_into("<QQQQ", header, 24, 1, backup_lba, (1 << 20) // sector, last_usable)
        struct.pack_into("<QIII", header, 72, 2, 128, 128, zlib.crc32(entries) & 0xffffffff)
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xffffffff)
        with path.open("wb") as stream:
            stream.truncate(4 << 30)
            stream.seek(sector)
            stream.write(header)
            stream.seek(2 * sector)
            stream.write(entries)
        return path

    def test_gpt_at_device_end_honors_reserved_tail_gap(self):
        for sector in (512, 4096):
            with self.subTest(sector=sector), tempfile.TemporaryDirectory() as directory:
                backup = (4 << 30) // sector - 1
                last = (4 << 30) // sector - (1 << 20) // sector
                path = self.gpt_fixture(directory, sector, backup, last)
                bounds = grower.gpt_bounds(path, sector, 4 << 30)
                self.assertEqual(bounds["last_usable_lba"], last)
                self.assertEqual(bounds["current_last_usable_lba"], last)
                self.assertGreater(bounds["physical_last_usable_lba"], last)

    def test_unrelocated_gpt_keeps_current_and_preview_bounds_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = (1 << 30) // 4096 - 1
            path = self.gpt_fixture(directory, 4096, backup, backup - 5)
            bounds = grower.gpt_bounds(path, 4096, 4 << 30)
            self.assertEqual(bounds["current_last_usable_lba"], backup - 5)
            self.assertEqual(bounds["last_usable_lba"], (4 << 30) // 4096 - 6)
            self.assertNotEqual(bounds["old_backup_lba"], bounds["new_backup_lba"])

    def test_gpt_valid_crc_with_unsafe_bounds_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = (4 << 30) // 4096 - 1
            path = self.gpt_fixture(directory, 4096, backup, backup - 2)
            with self.assertRaisesRegex(ValueError, "usable bounds"):
                grower.gpt_bounds(path, 4096, 4 << 30)

    def test_gpt_bad_crc_is_rejected_before_planning(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = (4 << 30) // 4096 - 1
            path = self.gpt_fixture(directory, 4096, backup, backup - 5)
            with path.open("r+b") as stream:
                stream.seek(4096 + 16)
                stream.write(bytes(4))
            with self.assertRaisesRegex(ValueError, "header CRC"):
                grower.gpt_bounds(path, 4096, 4 << 30)


class InstallerClaimTests(unittest.TestCase):
    def test_partition_reread_uses_the_owned_descriptor_without_reopening(self):
        import fcntl
        destination = mock.Mock()
        destination.fileno.return_value = 73
        with mock.patch.object(installer.os, "fsync") as sync, \
             mock.patch.object(fcntl, "ioctl") as ioctl, \
             mock.patch.object(installer, "run", side_effect=AssertionError("Must not start blockdev")):
            installer.reread_partition_table(destination)
        sync.assert_called_once_with(73)
        ioctl.assert_called_once_with(73, 0x125F, 0)
        destination.close.assert_not_called()

    def test_reread_error_propagates_without_releasing_claim(self):
        import fcntl
        destination = mock.Mock()
        destination.fileno.return_value = 73
        with mock.patch.object(installer.os, "fsync"), \
             mock.patch.object(fcntl, "ioctl", side_effect=OSError(errno.EBUSY, "device busy")), \
             mock.patch.object(installer, "run", side_effect=AssertionError("No reopen fallback")), \
             self.assertRaises(OSError) as raised:
            installer.reread_partition_table(destination)
        self.assertEqual(raised.exception.errno, errno.EBUSY)
        destination.close.assert_not_called()

    def partition_fixture(self):
        return [{"number": number, "start": number * 100, "end": number * 100 + 99,
                 "uuid": f"uuid-{number}", "type": "linux", "attributes": 4}
                for number in (1, 2, 3)]

    def test_growth_suppresses_all_external_partition_refresh(self):
        parts = self.partition_fixture()
        header = {"partitions": copy.deepcopy(parts), "last": 999}
        target = Path("/dev/sda")
        with mock.patch.object(installer, "gpt_header", return_value=header), \
             mock.patch.object(installer, "run") as run:
            installer.grow_root_partition(mock.Mock(), target, parts)
        run.assert_called_once_with("sfdisk", "--no-reread", "--no-tell-kernel", "--wipe", "never",
                                    "--wipe-partitions", "never", "-N", "3", target,
                                    input="start=300, size=700\n")

    def test_growth_refuses_changed_partition_before_writing(self):
        parts = self.partition_fixture()
        header = {"partitions": copy.deepcopy(parts), "last": 999}
        header["partitions"][2]["uuid"] = "unexpected"
        with mock.patch.object(installer, "gpt_header", return_value=header), \
             mock.patch.object(installer, "run") as run, \
             self.assertRaisesRegex(RuntimeError, "changed unexpectedly"):
            installer.grow_root_partition(mock.Mock(), Path("/dev/sda"), parts)
        run.assert_not_called()

    def test_source_growth_cannot_write_past_reviewed_image(self):
        reviewed = b"the reviewed image"
        source = mock.Mock(wraps=io.BytesIO(reviewed + b"unexpected appended bytes"))
        source.fileno.return_value = 73
        destination = io.BytesIO()
        before = SimpleNamespace(st_size=len(reviewed), st_mtime_ns=100)
        after = SimpleNamespace(st_size=len(reviewed) + 25, st_mtime_ns=101)
        with mock.patch.object(installer.os, "fstat", side_effect=(before, after)), \
             self.assertRaisesRegex(RuntimeError, "Source image changed"):
            installer.write_verified_image(source, destination, len(reviewed), hashlib.sha256(reviewed).hexdigest())
        self.assertEqual(destination.getvalue(), reviewed)

    def test_source_truncation_and_same_size_modification_are_rejected(self):
        expected = b"original image"
        for payload, message in ((b"short", "truncated"), (b"modified image", "Source image changed")):
            source = mock.Mock(wraps=io.BytesIO(payload))
            source.fileno.return_value = 73
            metadata = SimpleNamespace(st_size=len(expected), st_mtime_ns=100)
            with self.subTest(payload=payload), \
                 mock.patch.object(installer.os, "fstat", return_value=metadata), \
                 self.assertRaisesRegex(RuntimeError, message):
                installer.write_verified_image(source, io.BytesIO(), len(expected), hashlib.sha256(expected).hexdigest())


if __name__ == "__main__":
    unittest.main()
