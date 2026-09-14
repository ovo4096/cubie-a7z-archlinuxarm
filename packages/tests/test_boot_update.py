import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "runtime/a7z-boot-update"
LOADER = importlib.machinery.SourceFileLoader("a7z_boot_update", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
boot = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(boot)
KERNEL = "6.6.98-4-aw2511"
OLD = "default old\ntimeout 10\nlabel old\n linux /boot/old-image\n append root=UUID=old-root rw\n"


class BootUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("boot", "etc/kernel", f"usr/lib/modules/{KERNEL}", f"usr/lib/linux-image-{KERNEL}/allwinner"):
            (self.root / name).mkdir(parents=True)
        image = bytearray(64)
        image[56:60] = b"ARMd"
        (self.root / f"boot/vmlinuz-{KERNEL}").write_bytes(image)
        (self.root / f"boot/initramfs-{KERNEL}.img").write_bytes(b"original initramfs")
        (self.root / f"boot/config-{KERNEL}").write_text("\n".join(value + "=y" for value in boot.REQUIRED_BUILTINS) + "\n")
        (self.root / f"usr/lib/linux-image-{KERNEL}/allwinner/sun60i-a733-cubie-a7z.dtb").write_bytes(b"dtb")
        (self.root / f"usr/lib/modules/{KERNEL}/pkgbase").write_text("linux-radxa-a7z\n")
        (self.root / f"usr/lib/modules/{KERNEL}/wireless.ko").write_bytes(b"wireless module")
        (self.root / "etc/kernel/cmdline").write_text("root=UUID=@ROOT_UUID@ rw rootwait\n")

    def tearDown(self):
        self.temporary.cleanup()

    def test_append_preserves_existing_default_and_unmanaged_entry(self):
        result = boot.render_extlinux(OLD, KERNEL, "root=UUID=new-root rw")
        self.assertTrue(result.startswith(OLD.rstrip()))
        self.assertEqual(result.count("default "), 1)
        self.assertIn(f"fdtdir /usr/lib/linux-image-{KERNEL}/", result)
        self.assertEqual(boot.render_extlinux(result, KERNEL, "root=UUID=new-root rw"), result)

    def test_select_is_explicit_and_retains_old_entry(self):
        result = boot.render_extlinux(OLD, KERNEL, "root=UUID=new-root rw", True)
        self.assertIn(f"default a7z-{KERNEL}", result)
        self.assertIn("label old\n linux /boot/old-image", result)
        self.assertNotIn("default old", result)

    def test_hook_does_not_establish_default_on_blank_system(self):
        with contextlib.redirect_stdout(io.StringIO()):
            boot.update(KERNEL, root=self.root)
        path = self.root / "boot/extlinux/extlinux.conf"
        self.assertFalse(path.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            boot.update(KERNEL, select=True, root=self.root)
        self.assertIn(f"default a7z-{KERNEL}", path.read_text())

    def test_storage_configuration_failure_precedes_config_write(self):
        (self.root / f"boot/config-{KERNEL}").write_text("CONFIG_BLK_DEV_INITRD=y\n")
        with self.assertRaisesRegex(ValueError, "built-in storage configuration"):
            boot.update(KERNEL, select=True, root=self.root)
        self.assertFalse((self.root / "boot/extlinux/extlinux.conf").exists())

    def test_snapshot_restores_removed_kernel_and_network_modules(self):
        (self.root / "boot/extlinux").mkdir()
        menu = self.root / "boot/extlinux/extlinux.conf"
        menu.write_text(OLD)
        with contextlib.redirect_stdout(io.StringIO()):
            boot.snapshot(self.root)
        (self.root / f"boot/vmlinuz-{KERNEL}").unlink()
        (self.root / f"boot/initramfs-{KERNEL}.img").unlink()
        shutil.rmtree(self.root / f"usr/lib/modules/{KERNEL}")
        shutil.rmtree(self.root / f"usr/lib/linux-image-{KERNEL}")
        with contextlib.redirect_stdout(io.StringIO()):
            boot.restore_missing(self.root)
        self.assertEqual((self.root / f"usr/lib/modules/{KERNEL}/wireless.ko").read_bytes(), b"wireless module")
        self.assertEqual((self.root / f"boot/initramfs-{KERNEL}.img").read_bytes(), b"original initramfs")
        self.assertEqual(menu.read_text(), OLD)

    def test_release_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid kernel release"):
            boot.render_extlinux(OLD, "../../etc/passwd", "root=UUID=any")


if __name__ == "__main__":
    unittest.main()
