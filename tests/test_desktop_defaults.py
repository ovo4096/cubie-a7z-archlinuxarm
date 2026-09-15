"""Offline image defaults: user preservation, clean seeds and X11 scope."""
import configparser
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("a7z_desktop", REPO / "tools/desktop.py")
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)


class DesktopDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "image"
        self.root.mkdir()
        self.write("usr/share/applications/org.fcitx.Fcitx5.desktop",
                   "[Desktop Entry]\nType=Application\nName=Fcitx 5\nExec=fcitx5\n")
        self.write("usr/share/applications/a7z-chromium.desktop",
                   "[Desktop Entry]\nType=Application\nExec=/usr/bin/a7z-chromium -- %U\n")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_cli_performs_no_changes(self):
        self.write("etc/locale.conf", "LANG=C.UTF-8\n")
        before = self.snapshot()
        result = desktop.configure_desktop_defaults(self.root, "cli")
        self.assertFalse(result["configured"])
        self.assertEqual(before, self.snapshot())

    def test_gui_seeds_only_static_input_state_and_preserves_home(self):
        personal = self.write("home/alarm/.local/share/fcitx5/rime/user.yaml", "private fixture")
        for variant in ("xfce", "kde"):
            with self.subTest(variant=variant):
                desktop.configure_desktop_defaults(self.root, variant)
                seed = self.root / "etc/skel"
                profile = configparser.ConfigParser()
                profile.read(seed / ".config/fcitx5/profile")
                self.assertEqual(profile["Groups/0"]["DefaultIM"], "rime")
                self.assertEqual(profile["Groups/0/Items/0"]["Name"], "keyboard-us")
                self.assertEqual(profile["Groups/0/Items/1"]["Name"], "rime")
                rime = seed / ".local/share/fcitx5/rime"
                self.assertEqual([p.name for p in rime.iterdir()], ["default.custom.yaml"])
                self.assertIn("schema: luna_pinyin_simp", (rime / "default.custom.yaml").read_text())
                self.assertNotIn(b"private fixture", b"".join(p.read_bytes() for p in seed.rglob("*") if p.is_file()))
                self.assertEqual(personal.read_text(), "private fixture")
                self.assertEqual((seed / ".config/autostart/org.fcitx.Fcitx5.desktop").read_bytes(),
                                 (self.root / "usr/share/applications/org.fcitx.Fcitx5.desktop").read_bytes())
        self.assertTrue((seed / ".config/plasma-workspace/env/70-a7z-chinese.sh").is_file())

    def test_existing_prefs_disabled_autostart_and_locale_are_preserved(self):
        existing = {
            "etc/skel/.config/mimeapps.list": "[Default Applications]\ntext/html=firefox.desktop;\n",
            "etc/skel/.config/fcitx5/profile": "custom profile\n",
            "etc/skel/.config/autostart/org.fcitx.Fcitx5.desktop": "[Desktop Entry]\nHidden=true\n",
            "etc/skel/.xprofile": "# user custom environment\n",
            "etc/locale.conf": "LANG=en_US.UTF-8\n",
        }
        for path, content in existing.items():
            self.write(path, content)
        self.write("etc/locale.gen", "en_US.UTF-8 UTF-8\n#zh_CN.UTF-8 UTF-8\n")
        first = desktop.configure_desktop_defaults(self.root, "kde")
        for path, content in existing.items():
            self.assertEqual((self.root / path).read_text(), content)
            self.assertIn(path, first["preserved"])
        self.assertTrue(first["locale_gen_changed"])
        before = self.snapshot()
        second = desktop.configure_desktop_defaults(self.root, "kde")
        self.assertFalse(second["locale_gen_changed"])
        self.assertEqual(second["created"], [])
        self.assertEqual(before, self.snapshot())
        self.assertIn("en_US.UTF-8 UTF-8\n", (self.root / "etc/locale.gen").read_text())

    @unittest.skipUnless(os.name == "posix", "symlink ownership semantics require Linux")
    def test_symlink_parent_cannot_write_outside_image(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / "etc").mkdir()
        (self.root / "etc/skel").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink parent"):
            desktop.configure_desktop_defaults(self.root, "xfce")
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_runtime_entry_fails_before_creating_defaults(self):
        (self.root / "usr/share/applications/a7z-chromium.desktop").unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "desktop entries"):
            desktop.configure_desktop_defaults(self.root, "xfce")
        self.assertEqual(before, self.snapshot())

    def test_xfce_panel_browser_helper_and_custom_choice(self):
        desktop.configure_desktop_defaults(self.root, "xfce")
        seed = self.root / "etc/skel"
        chosen = (seed / ".config/xfce4/helpers.rc").read_text().strip().split("=", 1)[1]
        helper = configparser.ConfigParser(interpolation=None)
        helper.read(seed / f".local/share/xfce4/helpers/{chosen}.desktop")
        entry = helper["Desktop Entry"]
        self.assertEqual(entry["Type"], "X-XFCE-Helper")
        self.assertEqual(entry["X-XFCE-Category"], "WebBrowser")
        self.assertEqual(entry["X-XFCE-Commands"], "/usr/bin/a7z-chromium")
        self.assertEqual(entry["X-XFCE-CommandsWithParameter"], '/usr/bin/a7z-chromium -- "%s"')
        self.write("etc/skel/.config/xfce4/helpers.rc", "WebBrowser=firefox\n")
        desktop.configure_desktop_defaults(self.root, "xfce")
        self.assertEqual((seed / ".config/xfce4/helpers.rc").read_text(), "WebBrowser=firefox\n")

    @unittest.skipUnless(shutil.which("sh"), "requires a POSIX shell")
    def test_input_and_locale_environment_only_changes_x11(self):
        script = REPO / "desktop/x11-environment.sh"
        probe = '. "$1"; printf "%s|%s|%s|%s|%s" "$LANG" "${GTK_IM_MODULE-}" "${QT_IM_MODULE-}" "${XMODIFIERS-}" "${LC_ALL-}"'
        for display, session, expected in (
            ("", "tty", "C.UTF-8||||C.UTF-8"),
            (":0", "wayland", "C.UTF-8||||C.UTF-8"),
            (":0", "x11", "zh_CN.UTF-8|fcitx|fcitx|@im=fcitx|"),
        ):
            with self.subTest(session=session):
                environment = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                               "DISPLAY": display, "XDG_SESSION_TYPE": session}
                actual = subprocess.run(["sh", "-c", probe, "desktop-test", str(script)],
                                        env=environment, text=True, capture_output=True, check=True)
                self.assertEqual(actual.stdout, expected)


if __name__ == "__main__":
    unittest.main()
