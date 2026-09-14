import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rootfs_variants', Path(__file__).resolve().parents[1] / 'tools/rootfs.py')
rootfs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rootfs)

class VariantTests(unittest.TestCase):
    def test_cli_package_set_has_no_desktop_server_or_display_manager(self):
        packages = rootfs.variant_packages('cli')
        for item in ('xorg-server', 'xfce4', 'lightdm', 'sddm', 'plasma-desktop', 'mesa-utils'):
            self.assertNotIn(item, packages)
        for item in ('networkmanager', 'openssh', 'mkinitcpio', 'libdrm'):
            self.assertIn(item, packages)

    def test_legacy_desktop_is_xfce_and_conflicting_variant_fails(self):
        self.assertEqual(rootfs.selected_variant(types.SimpleNamespace(desktop=True, variant=None)), 'xfce')
        self.assertEqual(rootfs.selected_variant(types.SimpleNamespace(desktop=False, variant='kde')), 'kde')
        with self.assertRaises(ValueError):
            rootfs.selected_variant(types.SimpleNamespace(desktop=True, variant='cli'))

    def test_different_desktop_root_cannot_be_relabelled_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(rootfs.subprocess, 'check_output', return_value='base\nxfce4-session\n'):
                with self.assertRaises(ValueError):
                    rootfs.verify_variant(Path(directory), 'cli')

    def test_kde_requires_x11_and_does_not_set_global_library_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                rootfs.configure_kde(root)
            sessions = root / 'usr/share/xsessions'
            sessions.mkdir(parents=True)
            (sessions / 'plasmax11.desktop').write_text('[Desktop Entry]\nExec=/usr/bin/startplasma-x11\n')
            rootfs.configure_kde(root)
            self.assertIn('Enabled=false', (root / 'etc/xdg/kwinrc').read_text())
            self.assertIn('QT_QUICK_BACKEND=software', (root / 'etc/xdg/plasma-workspace/env/a7z-t5.sh').read_text())
            self.assertFalse((root / 'etc/environment').exists())
            self.assertNotIn('LD_LIBRARY_PATH', (root / 'etc/xdg/plasma-workspace/env/a7z-t5.sh').read_text())

    def test_known_legacy_lightdm_configuration_can_be_migrated_only_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'etc/lightdm/lightdm.conf.d/50-a7z-desktop.conf'
            path.parent.mkdir(parents=True)
            legacy = '[Seat:*]\ngreeter-session=lightdm-gtk-greeter\nuser-session=xfce\n'
            path.write_text(legacy)
            rootfs.managed_configuration(root, path.relative_to(root), legacy, legacy_content=legacy)
            self.assertTrue(path.read_text().startswith(rootfs.CONFIG_MARKER))
            path.write_text(legacy + 'autologin-user=someone\n')
            with self.assertRaises(ValueError):
                rootfs.managed_configuration(root, path.relative_to(root), legacy, legacy_content=legacy)

if __name__ == '__main__':
    unittest.main()
