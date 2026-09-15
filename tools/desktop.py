#!/usr/bin/env python3
"""Write offline Chinese desktop presets; never start applications or a chroot.

Presets live in /etc/skel so the release sanitizer can rebuild clean homes.
Existing preset files are preserved, including user-disabled autostart entries.
The caller installs packages and runs locale-gen inside the image afterwards.
"""
from pathlib import Path
import re


ASSETS = Path(__file__).resolve().parents[1] / "desktop"
DESKTOP_PACKAGES = (
    "fcitx5", "fcitx5-rime", "fcitx5-gtk", "fcitx5-qt",
    "fcitx5-configtool", "rime-luna-pinyin", "noto-fonts-cjk", "noto-fonts-emoji",
)
GUI_LOCALE = "zh_CN.UTF-8 UTF-8"
COMMON_PRESETS = {
    ".xprofile": "x11-environment.sh",
    ".config/fcitx5/profile": "fcitx5-profile",
    ".config/fcitx5/config": "fcitx5-config",
    ".local/share/fcitx5/rime/default.custom.yaml": "rime-default.custom.yaml",
    ".config/mimeapps.list": "mimeapps.list",
    ".config/fontconfig/conf.d/64-a7z-chinese.conf": "fontconfig.conf",
}


def _safe_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid desktop preset path")
    current = root
    for component in path.parts[:-1]:
        current /= component
        if current.is_symlink():
            raise ValueError("Desktop preset path has a symlink parent")
        if current.exists() and not current.is_dir():
            raise ValueError("Desktop preset path has a non-directory parent")
    return root / path


def _write_missing(root, relative, content, result):
    target = _safe_path(root, relative)
    if target.exists() or target.is_symlink():
        result["preserved"].append(relative)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    target.chmod(0o644)
    result["created"].append(relative)


def configure_desktop_defaults(root: Path, variant: str, user: str = "alarm") -> dict:
    """Seed XFCE/KDE images without changing existing homes or custom presets.

    ``user`` names the intended seed account for the caller's report. This
    function deliberately does not copy presets to that account: sanitize.py
    owns clean-home creation and uid/gid assignment. CLI performs no writes.
    ``locale_gen_changed`` reports only the locale.gen edit, not whether the
    locale archive is already compiled. Run locale-gen for every GUI finalize.
    """
    if variant not in ("cli", "xfce", "kde"):
        raise ValueError("Unknown image desktop variant")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", user):
        raise ValueError("Invalid seed account name")
    result = {"variant": variant, "user": user, "configured": variant != "cli",
              "created": [], "preserved": [], "locale_gen_changed": False}
    if variant == "cli":
        return result
    root = Path(root)
    if root.is_symlink():
        raise ValueError("Desktop image root must not be a symlink")
    root = root.resolve(strict=True)
    if root == Path(root.anchor):
        raise ValueError("Refusing to configure a live filesystem root")
    # Check installed entry points before writing a partially usable preset.
    upstream = _safe_path(root, "usr/share/applications/org.fcitx.Fcitx5.desktop")
    browser = _safe_path(root, "usr/share/applications/a7z-chromium.desktop")
    for required in (upstream, browser):
        if required.is_symlink() or not required.is_file():
            raise ValueError("Install Fcitx5 and A7Z Chromium desktop entries before finalizing")
    autostart = upstream.read_text(encoding="utf-8")
    if "[Desktop Entry]" not in autostart or "Exec=" not in autostart:
        raise ValueError("Installed Fcitx5 desktop entry is invalid")

    presets = dict(COMMON_PRESETS)
    if variant == "xfce":
        presets[".config/xfce4/helpers.rc"] = "xfce-helpers.rc"
        presets[".local/share/xfce4/helpers/a7z-chromium.desktop"] = "xfce-a7z-chromium.desktop"
    if variant == "kde":
        # Plasma reads this hook before launching/importing the GUI session.
        presets[".config/plasma-workspace/env/70-a7z-chinese.sh"] = "x11-environment.sh"
        presets[".config/plasma-localerc"] = "plasma-localerc"
    for relative, asset in presets.items():
        _write_missing(root, "etc/skel/" + relative,
                       (ASSETS / asset).read_text(encoding="utf-8"), result)
    _write_missing(root, "etc/skel/.config/autostart/org.fcitx.Fcitx5.desktop", autostart, result)
    # The console lacks CJK glyphs. Keep global messages usable on serial/TTY;
    # only GUI hooks below select the generated Chinese locale.
    _write_missing(root, "etc/locale.conf", "LANG=C.UTF-8\n", result)
    locale_gen = _safe_path(root, "etc/locale.gen")
    if locale_gen.is_symlink() or (locale_gen.exists() and not locale_gen.is_file()):
        raise ValueError("locale.gen must be a regular file")
    original = locale_gen.read_text(encoding="utf-8") if locale_gen.exists() else ""
    enabled = any(line.split("#", 1)[0].split() == GUI_LOCALE.split()
                  for line in original.splitlines())
    if not enabled:
        content = original + ("\n" if original and not original.endswith("\n") else "")
        content += "# Chinese desktop locale; console keeps its existing locale.\n" + GUI_LOCALE + "\n"
        locale_gen.parent.mkdir(parents=True, exist_ok=True)
        locale_gen.write_text(content, encoding="utf-8", newline="\n")
        result["locale_gen_changed"] = True
    return result
