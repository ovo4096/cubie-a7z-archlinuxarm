import importlib.machinery
import importlib.util
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import sanitize

loader = importlib.machinery.SourceFileLoader("keyring_init", str(REPO / "runtime/a7z-keyring-init"))
spec = importlib.util.spec_from_loader(loader.name, loader)
keyring_init = importlib.util.module_from_spec(spec)
loader.exec_module(keyring_init)


class SanitizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "rootfs"
        self.root.mkdir()
        self.write("etc/arch-release", "")
        self.write("usr/bin/pacman", "package executable")
        self.write("etc/passwd", "root:x:0:0::/root:/bin/bash\nalarm:x:1000:1000::/home/alarm:/bin/bash\nnobody:x:65534:65534::/:/usr/bin/nologin\n")
        self.write("etc/shadow", "root:!:1::::::\nalarm:public-test-hash:1::::::\n")
        self.write("etc/skel/.bashrc", "packaged defaults\n")
        self.write("usr/bin/a7z-keyring-init", "runtime installed")
        self.write(sanitize.SERVICE_PATH, "service installed")
        self.write("usr/share/pacman/keyrings/archlinuxarm.gpg", "packaged public keys")
        self.password = mock.patch.object(sanitize, "_password_matches", side_effect=lambda s: s == "public-test-hash")
        self.password.start()
        self.addCleanup(self.password.stop)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_dry_run_redacts_and_does_not_modify(self):
        sentinel = "secret-WIFI-value-do-not-print"
        p = self.write("etc/NetworkManager/system-connections/private-personal-name.nmconnection", sentinel)
        self.write("root/.bash_history", "private command")
        self.write("etc/pacman.d/gnupg/private-keys-v1.d/device.key", "build secret")
        self.write("config/wifi/private-name.nmconnection", sentinel)
        report = sanitize.sanitize_root(self.root)
        self.assertEqual(p.read_text(), sentinel)
        text = json.dumps(report)
        for private in (sentinel, "private-personal-name", "device.key", "private command", "public-test-hash"):
            self.assertNotIn(private, text)
        self.assertFalse(report["before"]["clean"])

    def test_apply_removes_identity_but_keeps_packaged_defaults_and_trust_sources(self):
        for name in ("root/.ssh/id_ed25519", "home/alarm/.bash_history", "home/old-user/private-note",
                     "etc/NetworkManager/system-connections/local.nmconnection", "var/lib/NetworkManager/secret_key",
                     "var/lib/systemd/random-seed", "etc/pacman.d/gnupg/private-keys-v1.d/secret.key",
                     "etc/ssh/ssh_host_ed25519_key", "config/a7z-private-seed.json", "config/hostname",
                     "var/lib/a7z/boot-snapshots/example/snapshot", "var/lib/a7z/gpt-backups/example/table",
                     "var/log/journal/private/log", "var/cache/pacman/pkg/cache.pkg.tar.zst"):
            self.write(name, "private identity")
        self.write("etc/machine-id", "fixed-build-identity")
        self.write("var/lib/dbus/machine-id", "fixed-build-identity")
        self.write("var/lib/pacman/local/example/files", "%FILES%\nhome/alarm/.bashrc\n\n")
        self.write("home/alarm/.bashrc", "personal modification")
        self.write("etc/ssh/sshd_config", "PermitRootLogin no\n")
        self.write("var/lib/a7z-package-snapshot.txt", "public versions")
        result = sanitize.sanitize_root(self.root, apply=True)
        self.assertTrue(result["after"]["clean"], result)
        self.assertEqual((self.root / "home/alarm/.bashrc").read_text(), "packaged defaults\n")
        self.assertFalse((self.root / "home/old-user").exists())
        self.assertEqual((self.root / "etc/machine-id").read_bytes(), b"")
        self.assertEqual(os.readlink(self.root / "var/lib/dbus/machine-id"), "/etc/machine-id")
        self.assertTrue((self.root / sanitize.SERVICE_LINK).is_symlink())
        self.assertEqual((self.root / "usr/share/pacman/keyrings/archlinuxarm.gpg").read_text(), "packaged public keys")
        self.assertEqual((self.root / "etc/ssh/sshd_config").read_text(), "PermitRootLogin no\n")
        self.assertEqual(sanitize.sanitize_root(self.root, apply=True)["before"]["pending_actions"], 0)

    def test_symlink_parent_refused_before_any_mutation(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep").write_text("untouched")
        (self.root / "var").mkdir()
        (self.root / "var/lib").symlink_to(outside, target_is_directory=True)
        p = self.write("etc/NetworkManager/system-connections/test.nmconnection", "keep until validated")
        with self.assertRaises(sanitize.HygieneError):
            sanitize.sanitize_root(self.root, apply=True)
        self.assertEqual(p.read_text(), "keep until validated")
        self.assertEqual((outside / "keep").read_text(), "untouched")

    def test_leaf_symlink_is_unlinked_without_touching_external_files(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep").write_text("untouched")
        (self.root / "root").symlink_to(outside, target_is_directory=True)
        sanitize.sanitize_root(self.root, apply=True)
        self.assertEqual((outside / "keep").read_text(), "untouched")
        self.assertFalse((self.root / "root").is_symlink())

    def test_nested_mount_refused(self):
        with mock.patch.object(sanitize, "_mount_targets", return_value=[self.root / "var/cache/pacman/pkg"]):
            with self.assertRaises(sanitize.HygieneError):
                sanitize.sanitize_root(self.root, apply=True)

    def test_readonly_loop_mount_audit_is_separate_from_apply(self):
        record = {"target": self.root, "options": ["ro", "relatime"], "fs_type": "ext4", "source": "/dev/loop7p3"}
        with mock.patch.object(sanitize, "_mount_records", return_value=[record]):
            self.assertEqual(sanitize.audit_root(self.root, allow_readonly_mount=True)["kind"], "public-rootfs-hygiene")
            with self.assertRaises(sanitize.HygieneError):
                sanitize.sanitize_root(self.root, apply=True)
        for changes in ({"options": ["rw"]}, {"source": "/dev/sda3"}, {"fs_type": "vfat"}):
            with self.subTest(changes=changes), mock.patch.object(sanitize, "_mount_records", return_value=[dict(record, **changes)]):
                with self.assertRaises(sanitize.HygieneError):
                    sanitize.audit_root(self.root, allow_readonly_mount=True)
        nested = dict(record, target=self.root / "dev", fs_type="devtmpfs")
        with mock.patch.object(sanitize, "_mount_records", return_value=[record, nested]):
            with self.assertRaises(sanitize.HygieneError):
                sanitize.audit_root(self.root, allow_readonly_mount=True)

    def test_missing_keyring_service_cannot_erase_build_key(self):
        (self.root / sanitize.SERVICE_PATH).unlink()
        key = self.write("etc/pacman.d/gnupg/private-keys-v1.d/keep.key", "must survive refused apply")
        with self.assertRaises(sanitize.HygieneError):
            sanitize.sanitize_root(self.root, apply=True)
        self.assertTrue(key.exists())

    def test_package_owned_home_file_without_restore_source_is_preserved(self):
        self.write("var/lib/pacman/local/example/files", "%FILES%\nhome/alarm/owned-file\n\n")
        path = self.write("home/alarm/owned-file", "package asset")
        with self.assertRaises(sanitize.HygieneError):
            sanitize.sanitize_root(self.root, apply=True)
        self.assertEqual(path.read_text(), "package asset")

    def test_personal_login_password_is_a_blocker_not_exported(self):
        self.write("etc/shadow", "root:!:1::::::\nalarm:personal-hash-never-export:1::::::\n")
        report = sanitize.audit_root(self.root)
        self.assertIn("public-password-policy-mismatch", report["blockers"])
        self.assertNotIn("personal-hash-never-export", json.dumps(report))
        with self.assertRaises(sanitize.HygieneError):
            sanitize.sanitize_root(self.root, apply=True)

    def test_misplaced_private_pem_still_blocks_after_standard_cleanup(self):
        self.write("opt/custom/private.pem", "-----BEGIN " + "PRIVATE KEY-----\nSYNTHETIC TEST DATA\n")
        report = sanitize.sanitize_root(self.root, apply=True)["after"]
        self.assertFalse(report["clean"])
        self.assertIn("private-key-material-present", report["blockers"])

    def test_output_rejects_private_evidence_and_seed_declarations(self):
        output = Path(self.temp.name) / "release"
        (output / "docs/diagnostics").mkdir(parents=True)
        (output / "docs/diagnostics/private-name.txt").write_text("do not echo")
        (output / "public.img.json").write_text('{"private_seed_included":true}')
        (output / "public.img.zst").write_bytes(b"not examined")
        report = sanitize.audit_output(output)
        self.assertFalse(report["clean"])
        self.assertEqual(report["opaque_artifacts_not_inspected"], 1)
        self.assertIn("private-seed-declared-in-metadata", report["findings"])
        self.assertNotIn("private-name", json.dumps(report))

    def test_firstboot_keyring_marks_only_after_both_commands_and_is_idempotent(self):
        runner = mock.Mock()
        self.assertTrue(keyring_init.initialize(self.root, runner))
        self.assertEqual([x.args[0] for x in runner.call_args_list], [["/usr/bin/pacman-key", "--init"], ["/usr/bin/pacman-key", "--populate"]])
        self.write("etc/pacman.d/gnupg/pubring.gpg", "public")
        self.write("etc/pacman.d/gnupg/trustdb.gpg", "trust")
        self.assertFalse(keyring_init.initialize(self.root, runner))
        self.assertEqual(runner.call_count, 2)
        (self.root / "var/lib/a7z/keyring-initialized").unlink()
        failed = mock.Mock(side_effect=[None, subprocess.CalledProcessError(1, "pacman-key")])
        with self.assertRaises(subprocess.CalledProcessError):
            keyring_init.initialize(self.root, failed)
        self.assertFalse((self.root / "var/lib/a7z/keyring-initialized").exists())

    @unittest.skipUnless(shutil.which("bsdtar"), "libarchive bsdtar required")
    def test_initramfs_main_cpio_is_checked_beyond_early_archive(self):
        def cpio(entries):
            result = bytearray()
            for name, contents in [*entries, ("TRAILER!!!", b"")]:
                filename = name.encode() + b"\0"
                fields = [0, 0o100600, 0, 0, 1, 0, len(contents), 0, 0, 0, 0, len(filename), 0]
                result.extend(b"070701" + "".join(f"{x:08x}" for x in fields).encode() + filename)
                result.extend(b"\0" * (-len(result) % 4))
                result.extend(contents)
                result.extend(b"\0" * (-len(result) % 4))
            result.extend(b"\0" * (-len(result) % 512))
            return bytes(result)
        boot = self.root / "boot"
        boot.mkdir()
        archive = boot / "initramfs-test.img"
        early = cpio([("early_cpio", b"1\n")])
        archive.write_bytes(early + gzip.compress(cpio([("init", b"fixture"), ("etc/shadow", b"root:*::::::: \n")])))
        safe = sanitize.audit_initramfs(self.root)
        self.assertTrue(safe["clean"])
        self.assertEqual(safe["locked_placeholder_shadow_files"], 1)
        archive.write_bytes(early + gzip.compress(cpio([("init", b"fixture"), ("etc/shadow", b"root:!$6$SYNTHETIC-NOT-A-REAL-HASH:::::::\n")])))
        self.assertFalse(sanitize.audit_initramfs(self.root)["clean"])
        archive.write_bytes(early + gzip.compress(cpio([("init", b"fixture"), ("etc/pacman.d/gnupg/private-keys-v1.d/test.key", b"synthetic")])))
        self.assertFalse(sanitize.audit_initramfs(self.root)["clean"])


if __name__ == "__main__":
    unittest.main()
