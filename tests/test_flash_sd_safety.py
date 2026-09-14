"""Exercise SD preflight refusals using fake sysfs/lsblk data; never open a disk."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("flash_sd", Path(__file__).resolve().parents[1] / "tools/flash_sd.py")
flash = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flash)
CID = "00112233445566778899aabbccddeeff"  # synthetic fixture, never a physical card identity
TARGET = Path("/dev/mmcblk1")


class FlashSDPreflightTests(unittest.TestCase):
    def inspect(self, *, target=TARGET, mode=stat.S_IFBLK, kind="SD", cid=CID,
                sector=512, capacity=128 * 1024**3, mounts=None,
                child_mounts=None, holders=(), child_holders=(), swaps=""):
        tree = {"blockdevices": [{"name": str(target), "mountpoints": mounts or [None],
                                  "children": [{"name": "/dev/mmcblk1p1", "mountpoints": child_mounts or [None]}]}]}

        def read_text(path, *args, **kwargs):
            name = str(path)
            if name.endswith("device/type"):
                return kind + "\n"
            if name.endswith("device/cid"):
                return cid + "\n"
            if name == "/proc/swaps":
                return "Filename Type Size Used Priority\n" + swaps
            raise AssertionError(f"Unexpected read: {name}")

        def directory(path):
            if str(path) == "/sys/class/block/mmcblk1/holders":
                return iter(holders)
            if str(path) == "/sys/class/block/mmcblk1p1/holders":
                return iter(child_holders)
            raise AssertionError(f"Unexpected directory: {path}")

        def output(*args):
            if args[0:2] == ("blockdev", "--getss"):
                return str(sector)
            if args[0:2] == ("blockdev", "--getsize64"):
                return str(capacity)
            if args[0] == "lsblk":
                return json.dumps(tree)
            raise AssertionError(f"Unexpected command: {args}")

        with mock.patch.object(Path, "stat", return_value=SimpleNamespace(st_mode=mode)), \
             mock.patch.object(Path, "read_text", read_text), \
             mock.patch.object(Path, "iterdir", directory), \
             mock.patch.object(flash, "output", output), \
             mock.patch.object(flash.os, "open", side_effect=AssertionError("No device opens are permitted in this test")):
            flash.inspect(target, CID, 4 * 1024**3)

    def test_expected_empty_sd_is_accepted_read_only(self):
        self.inspect()

    def test_refuse_partition_regular_file_and_non_sd(self):
        for kwargs in ({"target": Path("/dev/mmcblk1p1")}, {"mode": stat.S_IFREG}, {"kind": "MMC"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.inspect(**kwargs)

    def test_refuse_changed_card_wrong_sector_or_small_capacity(self):
        for kwargs in ({"cid": "0" * 32}, {"sector": 4096}, {"capacity": 1024**3}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.inspect(**kwargs)

    def test_refuse_mounts_on_device_or_child(self):
        for kwargs in ({"mounts": ["/"]}, {"child_mounts": [None, "/media/card"]}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "mounted"):
                self.inspect(**kwargs)

    def test_refuse_holders_on_device_or_child(self):
        for kwargs in ({"holders": [Path("dm-0")]}, {"child_holders": [Path("md0")]}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "holder"):
                self.inspect(**kwargs)

    def test_refuse_active_partition_swap(self):
        with self.assertRaisesRegex(ValueError, "swap"):
            self.inspect(swaps="/dev/mmcblk1p1 partition 9999 0 -2\n")


class FlashSDDefaultTests(unittest.TestCase):
    def test_default_only_verifies_image_and_inspects_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "fixture.img"
            contents = bytearray(1024)
            contents[512:520] = b"EFI PART"
            image.write_bytes(contents)
            expected = hashlib.sha256(contents).hexdigest()
            argv = ["flash_sd.py", "--image", str(image), "--target", str(TARGET), "--cid", CID, "--sha256", expected]
            with mock.patch("sys.argv", argv), \
                 mock.patch.object(flash.os, "geteuid", return_value=0, create=True), \
                 mock.patch.object(Path, "resolve", lambda path, **kwargs: path), \
                 mock.patch.object(flash, "inspect") as inspect, \
                 mock.patch.object(flash.os, "open", side_effect=AssertionError("Default must not open any destination")), \
                 mock.patch.object(flash.subprocess, "run", side_effect=AssertionError("Default must not flush/reread a device")), \
                 contextlib.redirect_stdout(io.StringIO()):
                flash.main()
            inspect.assert_called_once_with(TARGET, CID, len(contents))
            self.assertEqual(image.read_bytes(), bytes(contents))

    def test_checksum_failure_precedes_device_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "fixture.img"
            contents = bytearray(1024)
            contents[512:520] = b"EFI PART"
            image.write_bytes(contents)
            argv = ["flash_sd.py", "--image", str(image), "--target", str(TARGET), "--cid", CID, "--sha256", "0" * 64]
            with mock.patch("sys.argv", argv), \
                 mock.patch.object(flash.os, "geteuid", return_value=0, create=True), \
                 mock.patch.object(Path, "resolve", lambda path, **kwargs: path), \
                 mock.patch.object(flash, "inspect") as inspect, \
                 self.assertRaisesRegex(ValueError, "checksum mismatch"):
                flash.main()
            inspect.assert_not_called()

    def test_readback_digest_rejects_short_reads(self):
        with self.assertRaisesRegex(ValueError, "Unexpected end"):
            flash.digest(io.BytesIO(b"short"), 512)


if __name__ == "__main__":
    unittest.main()
