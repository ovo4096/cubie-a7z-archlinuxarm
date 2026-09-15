import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


PATH = Path(__file__).with_name("a7z-chromium")
SPEC = importlib.util.spec_from_loader("a7z_chromium", importlib.machinery.SourceFileLoader("a7z_chromium", str(PATH)))
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


class ChromiumLauncherTests(unittest.TestCase):
    def test_minimal_path_keeps_standard_profile_and_environment(self):
        original = {"HOME": "/home/example", "DISPLAY": ":0", "AN_UNRELATED_SETTING": "keep"}
        command, environment = LAUNCHER.launch_plan([], original)
        self.assertEqual(command, [
            "/usr/bin/chromium", "--ozone-platform=x11", "--use-gl=angle", "--use-angle=vulkan",
            "--enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan",
            "--no-default-browser-check",
        ])
        self.assertEqual(environment, dict(original, VK_DRIVER_FILES=LAUNCHER.ICD, VK_ICD_FILENAMES=LAUNCHER.ICD))
        self.assertNotIn("VK_DRIVER_FILES", original)
        self.assertFalse(any("LD_" in key for key in environment))
        self.assertFalse(any("sandbox" in arg or "debugging" in arg or "user-data-dir" in arg for arg in command))

    def test_effective_file_feature_list_is_preserved(self):
        configured = ["--enable-features=SystemFeature", "--enable-features=UserFeature,Vulkan:parameter/value"]
        command, _ = LAUNCHER.launch_plan([], {}, configured)
        merged = LAUNCHER.effective_switches(command[1:])["enable-features"]
        self.assertEqual(merged, "UserFeature,Vulkan:parameter/value,VulkanFromANGLE,DefaultANGLEVulkan")
        self.assertEqual(configured[0], "--enable-features=SystemFeature")

    def test_cli_precedence_and_quoted_url_are_preserved(self):
        arguments = ["--incognito", "--enable-features=Old", "--enable-features=CLI<Study", "file:///tmp/a b.html"]
        command, _ = LAUNCHER.launch_plan(arguments, {}, ["--enable-features=FileFeature"])
        self.assertIn("--incognito", command)
        self.assertIn("file:///tmp/a b.html", command)
        self.assertEqual(LAUNCHER.effective_switches(command[1:])["enable-features"],
                         "CLI<Study,Vulkan,VulkanFromANGLE,DefaultANGLEVulkan")
        self.assertEqual(sum(arg.startswith("--enable-features=") for arg in command), 1)

    def test_end_of_options_preserves_literal_arguments(self):
        tail = ["--", "--enable-features=ThisIsAFileName", "--disable-gpu"]
        command, _ = LAUNCHER.launch_plan(["--incognito", *tail], {})
        self.assertEqual(command[-3:], tail)
        self.assertEqual(LAUNCHER.effective_switches(command[1:])["enable-features"],
                         "Vulkan,VulkanFromANGLE,DefaultANGLEVulkan")

    def test_explicit_conflicts_are_reported_without_silently_rewriting(self):
        for configured in (["--disable-features=Other,Vulkan"], ["--use-angle=gl"], ["--disable-gpu"],
                           ["--ozone-platform=wayland"], ["-disable-gpu-rasterization"]):
            with self.subTest(configured=configured), self.assertRaises(ValueError):
                LAUNCHER.launch_plan([], {}, configured)
        command, _ = LAUNCHER.launch_plan(["--disable-features=Other"], {})
        self.assertIn("--disable-features=Other", command)

    def test_software_removes_only_exact_own_icd_and_adds_no_hardware_flags(self):
        original = {"VK_DRIVER_FILES": LAUNCHER.ICD, "VK_ICD_FILENAMES": "/custom/driver.json",
                    "LD_PRELOAD": "/custom/user.so"}
        command, environment = LAUNCHER.launch_plan(["--", "https://example.invalid"], original, software=True)
        self.assertEqual(command, ["/usr/bin/chromium", "--disable-gpu", "--", "https://example.invalid"])
        self.assertNotIn("VK_DRIVER_FILES", environment)
        self.assertEqual(environment["VK_ICD_FILENAMES"], "/custom/driver.json")
        self.assertEqual(environment["LD_PRELOAD"], "/custom/user.so")
        self.assertEqual(original["VK_DRIVER_FILES"], LAUNCHER.ICD)

    def test_software_preserves_multiple_custom_icds(self):
        custom = "/custom/one.json:" + LAUNCHER.ICD
        _, environment = LAUNCHER.launch_plan([], {"VK_DRIVER_FILES": custom}, software=True)
        self.assertEqual(environment["VK_DRIVER_FILES"], custom)

    def test_startup_prompt_is_suppressed_only_for_hardware_without_desktop_identity_override(self):
        original = {"CHROME_DESKTOP": "custom.desktop", "CHROME_WRAPPER": "/custom/launcher"}
        command, environment = LAUNCHER.launch_plan([], original)
        self.assertIn("--no-default-browser-check", command)
        self.assertEqual(environment["CHROME_DESKTOP"], original["CHROME_DESKTOP"])
        self.assertEqual(environment["CHROME_WRAPPER"], original["CHROME_WRAPPER"])
        command, environment = LAUNCHER.launch_plan([], original, software=True)
        self.assertNotIn("--no-default-browser-check", command)
        self.assertEqual(environment, original)

    def test_config_terminator_fails_before_options_can_be_ignored(self):
        with self.assertRaisesRegex(ValueError, "terminator"):
            LAUNCHER.launch_plan([], {}, ["--"])

    def test_same_switch_rules_and_explicit_profile_passthrough(self):
        command, _ = LAUNCHER.launch_plan(["-enable-features=Extra", "--user-data-dir=/tmp/explicit profile"], {})
        self.assertIn("--enable-features=Extra,Vulkan,VulkanFromANGLE,DefaultANGLEVulkan", command)
        self.assertIn("--user-data-dir=/tmp/explicit profile", command)

    def test_config_paths_match_official_launcher(self):
        self.assertEqual(LAUNCHER.flag_paths({"HOME": "/home/example"}),
                         [Path("/etc/chromium-flags.conf"), Path("/home/example/.config/chromium-flags.conf")])
        self.assertEqual(LAUNCHER.flag_paths({"HOME": "/home/example", "XDG_CONFIG_HOME": "/tmp/custom"})[-1],
                         Path("/tmp/custom/chromium-flags.conf"))

    def test_kde_fallback_and_input_method_environment_survives_both_modes(self):
        # Plasma menu launches and Konsole may carry different Qt defaults.
        # These do not authorize changing the desktop or its input method.
        kde = {"XDG_CURRENT_DESKTOP": "KDE", "QT_QUICK_BACKEND": "software",
               "LIBGL_ALWAYS_SOFTWARE": "1", "QSG_RHI_BACKEND": "vulkan",
               "VK_DRIVER_FILES": LAUNCHER.ICD,
               "GTK_IM_MODULE": "fcitx", "QT_IM_MODULE": "fcitx", "XMODIFIERS": "@im=fcitx"}
        original = dict(kde)
        command, child = LAUNCHER.launch_plan([], kde)
        for key, value in kde.items():
            self.assertEqual(child[key], value)
        self.assertEqual(child["VK_ICD_FILENAMES"], LAUNCHER.ICD)
        self.assertIn("--use-angle=vulkan", command)
        self.assertFalse(any(key.startswith("LD_") for key in child))
        command, child = LAUNCHER.launch_plan([], kde, software=True)
        self.assertIn("--disable-gpu", command)
        self.assertNotIn("VK_DRIVER_FILES", child)
        self.assertEqual(child, {key: value for key, value in kde.items() if key != "VK_DRIVER_FILES"})
        self.assertEqual(kde, original)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Use the same Linux GLib as the Arch launcher")
    def test_glib_tokenization_without_shell_expansion_or_file_changes(self):
        parse = LAUNCHER.glib_parser()
        contents = (b'# ignored\n--enable-features="A,B"\n'
                    b'--proxy-server="http://example.invalid/a b"\n'
                    b'"$HOME" "$(touch not-created)"\n"unbalanced\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chromium-flags.conf"
            path.write_bytes(contents)
            flags = LAUNCHER.read_flags([path, path.with_name("missing")], parse)
            self.assertEqual(flags, ["--enable-features=A,B", "--proxy-server=http://example.invalid/a b",
                                     "$HOME", "$(touch not-created)"])
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
