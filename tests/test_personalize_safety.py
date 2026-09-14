"""Seed handling tests use temporary regular files, never a real disk."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


personal = load("personalize", REPO / "tools/personalize.py")
first = load("firstboot", REPO / "runtime/a7z-firstboot")


class ProfileTests(unittest.TestCase):
    def test_known_wpa2_vector_and_no_plain_password(self):
        data = personal.wifi_profile("IEEE", "password")
        self.assertIn(b"f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e", data)
        self.assertNotIn(b"password", data)
        first.wifi_valid(data)

    def test_unicode_and_metacharacters_ssid_are_byte_encoded(self):
        name = "\u7f51\u7edc;\\[x]"
        data = personal.wifi_profile(name, "test-passphrase", True)
        self.assertIn(("ssid=" + ";".join(map(str, name.encode())) + ";\n").encode(), data)
        self.assertIn(b"hidden=true", data)

    def test_bad_ssid_password_hostname_are_refused(self):
        for ssid, password in (("x" * 33, "password"), ("x", "short"), ("x", "password\n"), ("", "password")):
            with self.assertRaises(ValueError):
                personal.wifi_profile(ssid, password)
        for value in ("../host", "bad\nname", "-bad", "bad-", "bad.domain"):
            with self.assertRaises(ValueError):
                personal.hostname_text(value)

    def test_password_file_must_be_private_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "password"
            path.write_text("test-passphrase\n")
            args = SimpleNamespace(password_file=str(path), password_stdin=False)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                personal.read_password(args)
            path.chmod(0o600)
            self.assertEqual(personal.read_password(args), "test-passphrase")
            link = Path(tmp) / "link"
            link.symlink_to(path)
            args.password_file = str(link)
            with self.assertRaises(OSError):
                personal.read_password(args)

    def test_device_and_output_overwrite_are_refused(self):
        with self.assertRaises(ValueError):
            personal.regular_open("/dev/null")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "same-private.img"
            image.write_bytes(b"sentinel")
            args = SimpleNamespace(image=str(image), output=str(image))
            with self.assertRaises(ValueError):
                personal.personalize(args, "password")
            self.assertEqual(image.read_bytes(), b"sentinel")


@unittest.skipUnless(os.geteuid() == 0, "ownership checks require Linux root")
class FirstbootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed = self.root / "config/wifi/headless.nmconnection"
        self.seed.parent.mkdir(parents=True)
        self.profile = personal.wifi_profile("fixture", "test-passphrase")
        self.seed.write_bytes(self.profile)
        self.dest = self.root / "etc/NetworkManager/system-connections/a7z-seed-headless.nmconnection"

    def tearDown(self):
        self.tmp.cleanup()

    def run_first(self, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            first.initialize(self.root, account=(1000, 1000, "/home/alarm"), keygen=lambda: None, **kwargs)
        self.assertNotIn("test-passphrase", output.getvalue())
        return output.getvalue()

    def test_import_modes_cleanup_keys_hostname_and_idempotency(self):
        (self.root / "config/ssh-authorized-keys").write_text("ssh-ed25519 AAAA test\n")
        (self.root / "config/hostname").write_text("a7z-fixture\n")
        seen = []
        self.run_first(set_hostname=seen.append)
        self.assertEqual(self.dest.read_bytes(), self.profile)
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o600)
        self.assertEqual(self.dest.stat().st_uid, 0)
        self.assertEqual((self.root / "home/alarm/.ssh/authorized_keys").stat().st_uid, 1000)
        self.assertEqual(seen, ["a7z-fixture"])
        self.assertFalse(self.seed.exists())
        self.assertFalse((self.root / "config/ssh-authorized-keys").exists())
        self.assertFalse((self.root / "config/hostname").exists())
        self.assertEqual(self.run_first(), "")

    def test_invalid_profile_does_not_leak_or_delete_seed(self):
        secret = "PRIVATE-TEST-SECRET"
        self.seed.write_text("[connection]\ntype=wifi\nid=test\n" + secret + "\n")
        with self.assertRaises(ValueError) as raised:
            self.run_first()
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(self.seed.exists())
        self.assertFalse(self.dest.exists())

    def test_existing_config_conflict_retains_both_and_no_marker(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b"existing-user-config")
        with self.assertRaises(ValueError):
            self.run_first()
        self.assertEqual(self.dest.read_bytes(), b"existing-user-config")
        self.assertTrue(self.seed.exists())
        self.assertFalse((self.root / "var/lib/a7z/firstboot-complete").exists())

    def test_retry_after_keygen_failure_preserves_seed_until_success(self):
        with self.assertRaises(RuntimeError):
            first.initialize(self.root, keygen=mock.Mock(side_effect=RuntimeError("keygen failed")))
        self.assertTrue(self.seed.exists())
        self.assertEqual(self.dest.read_bytes(), self.profile)
        self.run_first()
        self.assertFalse(self.seed.exists())

    def test_symlink_seed_or_destination_is_rejected(self):
        self.seed.unlink()
        self.seed.symlink_to(self.root / "elsewhere")
        with self.assertRaises(OSError):
            self.run_first()
        self.seed.unlink()
        self.seed.write_bytes(self.profile)
        self.dest.parent.mkdir(parents=True)
        self.dest.symlink_to(self.root / "elsewhere")
        with self.assertRaises(ValueError):
            self.run_first()


if __name__ == "__main__":
    unittest.main()
