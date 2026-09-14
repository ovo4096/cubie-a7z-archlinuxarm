"""Safety/selection tests; real ELF and runtime checks are performed on T5 data."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("package_gpu", Path(__file__).resolve().parents[1] / "tools/package_gpu.py")
GPU = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GPU)


class RootResolutionTests(unittest.TestCase):
    def test_absolute_symlink_stays_in_foreign_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "usr/lib").mkdir(parents=True)
            (root / "usr/lib/libexample.so.1").write_text("foreign library")
            (root / "lib").symlink_to("/usr/lib")
            (root / "usr/lib/libexample.so").symlink_to("/lib/libexample.so.1")
            self.assertEqual(GPU.rooted(root, "lib/libexample.so"), root / "usr/lib/libexample.so.1")

    def test_escape_and_loop_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "escape").symlink_to("../outside")
            (root / "loop").symlink_to("loop")
            for relative in ("escape", "loop", "../../outside"):
                with self.assertRaises(ValueError):
                    GPU.rooted(root, relative)


class PackageBoundaryTests(unittest.TestCase):
    def test_shared_paths_and_loaders_never_overwrite_arch(self):
        for path in ("lib/firmware/rgx.fw.36.56.104.183", "usr/lib/systemd/system/lightdm.service",
                     "etc/environment", "usr/local/lib/libvulkan.so.1", "usr/lib/libOpenCL.so.1",
                     "usr/lib/libxcvt.so.0", "usr/local/lib/pkgconfig/egl.pc"):
            self.assertIsNone(GPU.destination(path), path)
        for path in ("usr/local/lib/libEGL.so.1", "usr/lib/libVK_IMG.so.1", "usr/local/lib/dri/pvr_dri.so"):
            package, output = GPU.destination(path)
            self.assertEqual(package, "userspace")
            self.assertTrue(output.is_relative_to(GPU.PRIVATE))

    def test_xorg_modules_are_isolated(self):
        for path in ("usr/bin/Xorg", "usr/lib/xorg/modules/libglamoregl.so",
                     "usr/lib/xorg/modules/drivers/modesetting_drv.so"):
            package, output = GPU.destination(path)
            self.assertEqual(package, "xorg")
            self.assertTrue(output.is_relative_to(GPU.PRIVATE / "xorg"))

    def test_no_target_audit_never_claims_dependency_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            report = GPU.dependency_report({"userspace": Path(directory)}, None)
            self.assertEqual(report["status"], "unchecked")
            self.assertEqual(report["hardware_validation"], "not-run")

    @unittest.skipUnless(shutil.which("tar") and shutil.which("zstd"), "Linux archive tools required")
    def test_pacman_metadata_is_at_archive_root_and_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = []
            for number in (1, 2):
                stage, output = root / f"stage{number}", root / f"output{number}"
                stage.mkdir()
                output.mkdir()
                GPU.write(stage, "usr/share/test/value", "fixed payload\n")
                package = GPU.archive(stage, output, "gpu-test", "1-1", [], 1000000000)
                members = GPU.run("tar", "-tf", str(package)).splitlines()
                self.assertIn(".PKGINFO", members)
                self.assertNotIn("./.PKGINFO", members)
                hashes.append(GPU.sha256(package))
            self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
