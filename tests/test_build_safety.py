"""Checks for orchestration guards without invoking pacman or touching disks."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("a7z_build", REPO / "tools/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildSafetyTests(unittest.TestCase):
    def test_refuses_system_roots_and_devices(self):
        for path in ("/", "/root", "/usr", "/dev/sda", "/proc/sys", "/sys/class"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                builder.safe_directory(path, "test")

    def test_nonempty_extract_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rootfs"
            target.mkdir()
            sentinel = target / "user-data"
            sentinel.write_text("preserve me")
            with patch.object(builder, "run") as run, self.assertRaisesRegex(ValueError, "empty"):
                builder.extract_empty(Path(directory) / "unused.tar", target)
            run.assert_not_called()
            self.assertEqual(sentinel.read_text(), "preserve me")

    def test_path_traversal_archive_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("/etc/shadow", "../escape", "usr/../../escape"):
                path = Path(directory) / "bad.tar"
                with tarfile.open(path, "w") as archive:
                    entry = tarfile.TarInfo(name)
                    entry.size = 4
                    archive.addfile(entry, io.BytesIO(b"test"))
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe"):
                    builder.validate_archive_names(path)

    def test_private_seed_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keys").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "regular"):
                builder.seed_fingerprint(root)

    def test_copy_refuses_different_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "output"
            source.write_bytes(b"new")
            output.write_bytes(b"user-data")
            with self.assertRaisesRegex(ValueError, "existing"):
                builder.copy_verified(source, output)
            self.assertEqual(output.read_bytes(), b"user-data")

    def test_runtime_audit_distinguishes_pacman_sandbox_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/pacman.conf").write_text(
                "[options]\nDownloadUser = alpm\nDisableSandboxFilesystem\n"
                "# DisableSandbox\n# DisableSandboxSyscalls\n[custom]\nDisableSandboxSyscalls\n")
            observed = builder.runtime_configuration(root)["pacman"]
            self.assertEqual(observed, {"download_user": "alpm", "disable_all_sandbox": False,
                                        "disable_filesystem_sandbox": True, "disable_syscall_sandbox": False})

    def test_runtime_audit_records_xorg_command_and_stable_kms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lightdm = root / "etc/lightdm/lightdm.conf.d"
            xorg = root / "etc/X11/xorg.conf.d"
            lightdm.mkdir(parents=True)
            xorg.mkdir(parents=True)
            (lightdm / "a7z.conf").write_text("xserver-command=/usr/lib/radxa-a7z-gpu/arch-Xorg -core\n")
            (xorg / "a7z.conf").write_text('    Option "kmsdev" "/dev/dri/by-path/platform-soc@3000000:sunxi-drm-card"\n')
            settings = {record["setting"] for record in builder.runtime_configuration(root)["desktop"]}
            self.assertIn("xserver-command=/usr/lib/radxa-a7z-gpu/arch-Xorg -core", settings)
            self.assertIn('Option "kmsdev" "/dev/dri/by-path/platform-soc@3000000:sunxi-drm-card"', settings)


if __name__ == "__main__":
    unittest.main()
