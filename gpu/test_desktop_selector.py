import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("desktop_selector", Path(__file__).with_name("a7z-gpu-desktop.py"))
DESKTOP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESKTOP)


class DesktopSelectorTests(unittest.TestCase):
    def prepare(self, root):
        for relative in ("usr/lib/Xorg", "etc/lightdm/lightdm.conf", "usr/bin/sddm", "usr/bin/a7z-gpu-run",
                         "usr/lib/radxa-a7z-gpu/lib/libEGL.so.1", "usr/lib/radxa-a7z-gpu/arch-Xorg"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("existing package payload\n")

    def test_switch_and_disable_preserve_package_and_main_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            originals = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            DESKTOP.apply(root, "arch-software")
            self.assertIn('"none"', (root / DESKTOP.XORG).read_text())
            DESKTOP.apply(root, "arch-glamor")
            self.assertIn("/usr/lib/radxa-a7z-gpu/arch-Xorg -core", (root / DESKTOP.LIGHTDM).read_text())
            self.assertIn('"AutoAddGPU" "false"', (root / DESKTOP.XORG).read_text())
            self.assertIn(DESKTOP.KMS_DEVICE, (root / DESKTOP.XORG).read_text())
            DESKTOP.apply(root, None)
            self.assertFalse((root / DESKTOP.XORG).exists())
            self.assertFalse((root / DESKTOP.LIGHTDM).exists())
            self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_upgrades_existing_managed_v1_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            for relative, text in {
                DESKTOP.XORG: DESKTOP.MARKER + 'Section "Device"\n    Driver "modesetting"\n    Option "AccelMethod" "none"\nEndSection\n',
                DESKTOP.LIGHTDM: DESKTOP.MARKER + '[Seat:*]\nxserver-command=/usr/bin/a7z-gpu-run /usr/lib/Xorg -core\n',
            }.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text(text)
            DESKTOP.apply(root, "arch-glamor")
            self.assertIn(DESKTOP.KMS_DEVICE, (root / DESKTOP.XORG).read_text())
            self.assertIn('"ShadowFB" "false"', (root / DESKTOP.XORG).read_text())
            self.assertIn(DESKTOP.ARCH_LAUNCHER, (root / DESKTOP.LIGHTDM).read_text())

    def test_unmanaged_configuration_prevents_any_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            config = root / DESKTOP.LIGHTDM
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("# User's own configuration\n")
            with self.assertRaises(ValueError):
                DESKTOP.apply(root, "arch-software")
            self.assertEqual(config.read_text(), "# User's own configuration\n")
            self.assertFalse((root / DESKTOP.XORG).exists())

    def test_sddm_uses_x11_launcher_and_removes_only_managed_lightdm_fragment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare(root)
            DESKTOP.apply(root, "arch-glamor")
            DESKTOP.apply(root, "arch-glamor", "sddm")
            text = (root / DESKTOP.SDDM).read_text()
            self.assertIn('DisplayServer=x11', text)
            self.assertIn('ServerPath=' + DESKTOP.ARCH_LAUNCHER, text)
            self.assertIn('GreeterEnvironment=QT_QUICK_BACKEND=software', text)
            self.assertNotIn('LD_LIBRARY_PATH', text)
            self.assertFalse((root / DESKTOP.LIGHTDM).exists())
            self.assertIn(DESKTOP.KMS_DEVICE, (root / DESKTOP.XORG).read_text())
            DESKTOP.apply(root, "arch-software", "sddm")
            self.assertIn('ServerPath=/usr/lib/Xorg', (root / DESKTOP.SDDM).read_text())


if __name__ == "__main__":
    unittest.main()
