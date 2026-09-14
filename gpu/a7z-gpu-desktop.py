#!/usr/bin/env python3
"""Explicit LightDM/SDDM selector for stock Arch Xorg; never restarts services."""
import argparse
import json
import os
from pathlib import Path

MARKER = "# Managed by a7z-gpu-desktop; remove with a7z-gpu-desktop disable.\n"
XORG = Path("etc/X11/xorg.conf.d/20-a7z-desktop.conf")
LIGHTDM = Path("etc/lightdm/lightdm.conf.d/70-a7z-desktop.conf")
SDDM = Path("etc/sddm.conf.d/70-a7z-desktop.conf")
ARCH_LAUNCHER = "/usr/lib/radxa-a7z-gpu/arch-Xorg"
KMS_DEVICE = "/dev/dri/by-path/platform-soc@3000000:sunxi-drm-card"


def configuration(mode, display_manager="lightdm"):
    acceleration = "none" if mode == "arch-software" else "glamor"
    command = "/usr/lib/Xorg -core" if mode == "arch-software" else ARCH_LAUNCHER + " -core"
    shadow = "true" if mode == "arch-software" else "false"
    result = {
        XORG: MARKER + f'''Section "Device"
    Identifier "A7Z Arch modesetting"
    Driver "modesetting"
    Option "kmsdev" "{KMS_DEVICE}"
    Option "AccelMethod" "{acceleration}"
    Option "ShadowFB" "{shadow}"
EndSection

Section "ServerFlags"
    Option "AutoAddGPU" "false"
EndSection
''',
    }
    if display_manager == "lightdm":
        result[LIGHTDM] = MARKER + f"[Seat:*]\nxserver-command={command}\n"
    else:
        server = "/usr/lib/Xorg" if mode == "arch-software" else ARCH_LAUNCHER
        result[SDDM] = MARKER + f'''[General]
DisplayServer=x11
GreeterEnvironment=QT_QUICK_BACKEND=software,LIBGL_ALWAYS_SOFTWARE=1

[X11]
ServerPath={server}
ServerArguments=-nolisten tcp -core
SessionDir=/usr/share/xsessions

[Wayland]
SessionDir=/usr/share/a7z/disabled-wayland-sessions
'''
    return result


def apply(root, mode, display_manager="lightdm"):
    required = ["usr/lib/Xorg", "usr/bin/sddm" if display_manager == "sddm" else "etc/lightdm/lightdm.conf"]
    if mode == "arch-glamor":
        required += ["usr/bin/a7z-gpu-run", "usr/lib/radxa-a7z-gpu/lib/libEGL.so.1", ARCH_LAUNCHER.lstrip("/")]
    if mode:
        for relative in required:
            if not (root / relative).is_file():
                raise ValueError(f"Required file missing: {root / relative}")
    files = (XORG, LIGHTDM, SDDM)
    for relative in files:
        path = root / relative
        if path.is_symlink() or (path.exists() and not path.read_text().startswith(MARKER)):
            raise ValueError(f"Refusing to replace a file not owned by this selector: {path}")
    if mode:
        selected = configuration(mode, display_manager)
        for relative, content in selected.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".conf.new")
            # Never follow an existing temporary symlink or truncate another file.
            with temporary.open("x") as stream:
                stream.write(content)
            temporary.chmod(0o644)
            temporary.replace(path)
        for relative in set(files) - set(selected):
            (root / relative).unlink(missing_ok=True)
        if display_manager == "sddm":
            (root / "usr/share/a7z/disabled-wayland-sessions").mkdir(parents=True, exist_ok=True)
    else:
        for relative in files:
            (root / relative).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"), help="offline image root; default changes the installed system")
    parser.add_argument("--display-manager", choices=("lightdm", "sddm"), default="lightdm")
    parser.add_argument("action", choices=("status", "print", "enable", "disable"))
    parser.add_argument("mode", choices=("arch-software", "arch-glamor"), nargs="?")
    args = parser.parse_args()
    if args.action in ("print", "enable") and args.mode is None:
        parser.error("print/enable require arch-software or arch-glamor")
    if args.action in ("status", "disable") and args.mode:
        parser.error("status/disable do not take a mode")
    root = args.root.resolve()
    if args.action == "print":
        print(json.dumps({str(path): value for path, value in configuration(args.mode, args.display_manager).items()}, indent=2))
        return 0
    if args.action == "status":
        print(json.dumps({str(path): (root / path).read_text() if (root / path).is_file() else None for path in (XORG, LIGHTDM, SDDM)}, indent=2))
        return 0
    if root == Path("/") and os.geteuid() != 0:
        parser.error("use sudo to change installed LightDM/Xorg configuration")
    try:
        apply(root, args.mode if args.action == "enable" else None, args.display_manager)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Configuration updated. No display service was restarted; the selection applies at its next start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
