#!/usr/bin/env python3
"""Prepare an isolated Arch Linux ARM root filesystem on a Linux build host."""
import argparse
import contextlib
import json
import os
import platform
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

BASE_PACKAGES = [
    "base", "openssh", "sudo", "networkmanager", "wpa_supplicant", "wireless-regdb",
    "bluez", "bluez-utils", "mkinitcpio", "e2fsprogs", "dosfstools", "util-linux",
    "python", "libdrm", "libx11", "libxcb", "libxshmfence", "vulkan-icd-loader",
    "vulkan-tools",
    "gptfdisk", "cloud-guest-utils",
    "curl", "wget", "zstd",
]
GUI_PACKAGES = ["xorg-server", "xorg-xrandr", "xf86-input-libinput", "mesa", "mesa-utils", "libglvnd",
                "ttf-dejavu", "noto-fonts-cjk", "noto-fonts-emoji", "chromium",
                "fcitx5", "fcitx5-rime", "fcitx5-gtk", "fcitx5-qt", "fcitx5-configtool", "rime-luna-pinyin",
                "gstreamer", "gst-plugins-base", "gst-plugins-good", "gst-plugins-bad",
                "pipewire-pulse", "pipewire-alsa", "wireplumber"]
VARIANT_PACKAGES = {
    "cli": [],
    "xfce": GUI_PACKAGES + ["xfce4", "lightdm", "lightdm-gtk-greeter", "network-manager-applet",
                            "pavucontrol", "xfce4-pulseaudio-plugin", "xdg-desktop-portal-gtk", "mousepad"],
    "kde": GUI_PACKAGES + ["plasma-desktop", "plasma-x11-session", "sddm", "plasma-nm",
                           "plasma-pa", "kscreen", "dolphin", "konsole", "kate", "ark",
                           "pipewire-pulse", "wireplumber", "xdg-desktop-portal-kde"],
}
IMAGE_VARIANT = "etc/a7z/image-variant"
CONFIG_MARKER = "# Managed by a7z rootfs builder.\n"


def ensure_binfmt():
    """WSL drops kernel binfmt registrations when its VM stops between builds."""
    if platform.machine().lower() in ("aarch64", "arm64"):
        return
    handler = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")
    contents = handler.read_text() if handler.is_file() else ""
    if contents.startswith("enabled\n") and any(line.startswith("flags:") and "F" in line for line in contents.splitlines()):
        return
    registrar = Path("/usr/lib/systemd/systemd-binfmt")
    config = Path("/usr/lib/binfmt.d/qemu-aarch64.conf")
    if not registrar.is_file() or not config.is_file():
        raise ValueError("Install qemu-user-static/binfmt support before building AArch64 roots")
    subprocess.run([str(registrar), str(config)], check=True)
    contents = handler.read_text() if handler.is_file() else ""
    if not contents.startswith("enabled\n") or not any(line.startswith("flags:") and "F" in line for line in contents.splitlines()):
        raise ValueError("qemu-aarch64 registration requires the F flag for chroot")


def selected_variant(args):
    variant = getattr(args, "variant", None)
    if getattr(args, "desktop", False):
        if variant and variant != "xfce":
            raise ValueError("--desktop is the legacy XFCE alias; do not combine it with a different --variant")
        variant = "xfce"
    return variant or "cli"


def variant_packages(variant):
    return list(dict.fromkeys(BASE_PACKAGES + VARIANT_PACKAGES[variant]))


def verify_variant(root, variant):
    marker = root / IMAGE_VARIANT
    if marker.exists() and marker.read_text().strip() != variant:
        raise ValueError("Rootfs variant differs; extract a fresh Arch seed instead of reusing another desktop")
    installed = subprocess.check_output(["chroot", str(root), "/usr/bin/pacman", "-Qq"], text=True).splitlines()
    forbidden = {"cli": {"xorg-server", "xfce4-session", "lightdm", "sddm", "plasma-desktop", "plasma-workspace"},
                 "xfce": {"sddm", "plasma-desktop", "plasma-workspace"},
                 "kde": {"xfce4-session", "xfce4-panel", "lightdm", "lightdm-gtk-greeter"}}[variant]
    conflicts = sorted(forbidden.intersection(installed))
    if conflicts:
        raise ValueError(f"Fresh {variant} rootfs required; incompatible installed packages: {conflicts}")


def managed_configuration(root, relative, content, legacy_content=None):
    path = root / relative
    if path.is_symlink() or (path.exists() and not path.read_text().startswith(CONFIG_MARKER)
                             and path.read_text() != legacy_content):
        raise ValueError(f"Refusing to overwrite unmanaged configuration: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_MARKER + content)


def configure_kde(root):
    sessions = list((root / "usr/share/xsessions").glob("*.desktop"))
    if not any("startplasma-x11" in path.read_text() for path in sessions):
        raise ValueError("Official Plasma X11 session missing; this T5 profile cannot silently switch to Wayland")
    # An AC-powered development board should stay reachable while idle.
    # This is a user-overridable PowerDevil default, not a system sleep ban;
    # leave display blanking, locking and explicit sleep actions unchanged.
    managed_configuration(root, "etc/xdg/powerdevilrc",
                          "[AC][SuspendAndShutdown]\nAutoSuspendAction=0\n")
    # KWin's T5 EGL window-surface path crashes; keep its compositor disabled.
    # The session default also provides a rollback when the Vulkan overrides
    # below are disabled. No private EGL/GBM search path enters the session.
    managed_configuration(root, "etc/xdg/kwinrc", "[Compositing]\nEnabled=false\n")
    managed_configuration(root, "etc/xdg/plasma-workspace/env/a7z-t5.sh",
                          "export QT_QUICK_BACKEND=software\nexport LIBGL_ALWAYS_SOFTWARE=1\n")
    # Breeze needs scene-graph effects that Qt's QPainter backend omits.
    # Retain Mesa CPU rendering as the greeter fallback, after the GPU
    # helper's generic 70-a7z-desktop.conf.
    managed_configuration(root, "etc/sddm.conf.d/80-a7z-kde-greeter.conf",
                          "[General]\nGreeterEnvironment=LIBGL_ALWAYS_SOFTWARE=1,QSG_RHI_BACKEND=opengl\n")
    # The private Vulkan ICD has its own RUNPATH and needs no LD_* variables.
    # Override only the greeter and shell; keep upstream Plasma ExecStart and
    # its D-Bus service behavior. KIO-launched applications may inherit QSG/VK.
    managed_configuration(root, "etc/sddm.conf.d/90-a7z-kde-vulkan.conf",
                          "[General]\nGreeterEnvironment=VK_DRIVER_FILES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json,QSG_RHI_BACKEND=vulkan\n")
    managed_configuration(root, "etc/systemd/user/plasma-plasmashell.service.d/90-a7z-kde-vulkan.conf",
                          "[Service]\n"
                          "UnsetEnvironment=QT_QUICK_BACKEND LIBGL_ALWAYS_SOFTWARE LD_LIBRARY_PATH LD_PRELOAD LIBGL_DRIVERS_PATH GBM_BACKENDS_PATH\n"
                          "Environment=QSG_RHI_BACKEND=vulkan\n"
                          "Environment=VK_DRIVER_FILES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json\n")
    if (root / "usr/share/sddm/themes/breeze/Main.qml").is_file():
        managed_configuration(root, "etc/sddm.conf.d/50-a7z-kde.conf", "[Theme]\nCurrent=breeze\n")


def configure_hdmi_compat(root, variant):
    if variant == "cli":
        return
    if not (root / "usr/bin/a7z-hdmi-compat").is_file():
        raise ValueError("HDMI compatibility helper missing; install radxa-a7z-base 0.1.0-5 or newer")
    if variant == "kde":
        managed_configuration(root, "etc/sddm.conf.d/95-a7z-hdmi-compat.conf",
                              "[X11]\n"
                              "DisplayCommand=/usr/bin/a7z-hdmi-compat --sddm\n"
                              "DisplayStopCommand=/usr/bin/a7z-hdmi-compat --sddm --stop\n")
    else:
        managed_configuration(root, "etc/lightdm/lightdm.conf.d/95-a7z-hdmi-compat.conf",
                              "[Seat:*]\n"
                              "display-setup-script=/usr/bin/a7z-hdmi-compat --lightdm\n"
                              "display-stopped-script=/usr/bin/a7z-hdmi-compat --lightdm --stop\n")


def run(args, **kwargs):
    print("+ " + shlex.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def validate_root(root):
    root = root.resolve()
    if root in (Path("/"), Path("/root"), Path("/home"), Path("/usr")):
        raise ValueError("Refusing an unsafe rootfs path")
    if not (root / "etc/arch-release").exists() or not (root / "usr/bin/pacman").is_file():
        raise ValueError(f"Not an extracted Arch rootfs: {root}")
    return root


@contextlib.contextmanager
def chroot_mounts(root, package_dirs=(), cache=None):
    mounts = []
    resolver = root / "etc/resolv.conf"
    old_link = os.readlink(resolver) if resolver.is_symlink() else None
    old_content = resolver.read_bytes() if resolver.is_file() and not resolver.is_symlink() else None
    try:
        # libalpm CheckSpace needs a mount at the chroot's / in mountinfo.
        run(["mount", "--bind", root, root])
        mounts.append(root)
        for source, relative in [("/dev", "dev"), ("/sys", "sys")]:
            target = root / relative
            target.mkdir(exist_ok=True)
            run(["mount", "--rbind", source, target])
            mounts.append(target)
            run(["mount", "--make-rslave", target])
        (root / "proc").mkdir(exist_ok=True)
        run(["mount", "-t", "proc", "proc", root / "proc"])
        mounts.append(root / "proc")
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            target = root / "var/cache/pacman/pkg"
            target.mkdir(parents=True, exist_ok=True)
            run(["mount", "--bind", cache, target])
            mounts.append(target)
        for index, directory in enumerate(package_dirs):
            target = root / f".a7z-packages-{index}"
            target.mkdir(exist_ok=True)
            run(["mount", "--bind", directory.resolve(), target])
            mounts.append(target)
            run(["mount", "-o", "remount,bind,ro", target])
        if resolver.exists() or resolver.is_symlink():
            resolver.unlink()
        resolver.write_bytes(Path("/etc/resolv.conf").read_bytes())
        yield
    finally:
        for home in ("/etc/pacman.d/gnupg", None):
            command = ["chroot", str(root), "/usr/bin/gpgconf"]
            if home:
                command += ["--homedir", home]
            subprocess.run([*command, "--kill", "all"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
        if resolver.exists() or resolver.is_symlink():
            resolver.unlink()
        if old_link is not None:
            resolver.symlink_to(old_link)
        elif old_content is not None:
            resolver.write_bytes(old_content)
        failed = []
        for target in reversed(mounts):
            # gpgconf requests daemon shutdown; allow that rootfs's agent to exit.
            for attempt in range(10):
                result = subprocess.run(["umount", "-R", str(target)], capture_output=True, text=True)
                if result.returncode == 0:
                    break
                time.sleep(0.2)
            if result.returncode:
                failed.append(f"{target}: {result.stderr.strip()}")
        if failed:
            raise RuntimeError("Rootfs mounts still busy; do not sanitize or package this rootfs: " + "; ".join(failed))


def chroot(root, args, **kwargs):
    return run(["chroot", root, *args], **kwargs)


def bootstrap(args):
    root = validate_root(args.rootfs)
    variant = selected_variant(args)
    verify_variant(root, variant)
    mirror = args.mirror.rstrip("/")
    (root / "etc/pacman.d/mirrorlist").write_text(f"Server = {mirror}/$arch/$repo\n")
    with chroot_mounts(root, cache=args.package_cache):
        chroot(root, ["/usr/bin/pacman-key", "--init"])
        chroot(root, ["/usr/bin/pacman-key", "--populate", "archlinuxarm"])
        installed = subprocess.run(["chroot", str(root), "/usr/bin/pacman", "-Q", "linux-aarch64"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if installed.returncode == 0:
            chroot(root, ["/usr/bin/pacman", "-R", "--noconfirm", "linux-aarch64"])
        packages = variant_packages(variant)
        chroot(root, ["/usr/bin/pacman", "--disable-sandbox", "-Syu", "--noconfirm", "--needed", *packages])
        chroot(root, ["/usr/bin/pacman", "-Q"], stdout=(root / "var/lib/a7z-package-snapshot.txt").open("w"))
    verify_variant(root, variant)
    (root / IMAGE_VARIANT).parent.mkdir(parents=True, exist_ok=True)
    (root / IMAGE_VARIANT).write_text(variant + "\n")


def install(args):
    root = validate_root(args.rootfs)
    package_dirs = [x.resolve() for x in args.package_dir]
    packages = []
    for index, directory in enumerate(package_dirs):
        for archive in sorted(directory.glob("*.pkg.tar.zst")):
            packages.append(f"/.a7z-packages-{index}/{archive.name}")
    if not packages:
        raise ValueError("No pacman packages found")
    with chroot_mounts(root, package_dirs, args.package_cache):
        chroot(root, ["/usr/bin/pacman", "--disable-sandbox", "-U", "--noconfirm", *packages])
        if (root / "usr/bin/a7z-boot-update").exists():
            # The package post-transaction hook has generated the matching image.
            chroot(root, ["/usr/bin/a7z-boot-update", "--select"])
        output = chroot(root, ["/usr/bin/pacman", "-Q"], capture_output=True, text=True)
        (root / "var/lib/a7z-package-snapshot.txt").write_text(output.stdout)


def finalize(args):
    root = validate_root(args.rootfs)
    variant = selected_variant(args)
    verify_variant(root, variant)
    if variant == "kde":
        configure_kde(root)
    if variant != "cli":
        from desktop import configure_desktop_defaults
        configure_desktop_defaults(root, variant)
        configure_hdmi_compat(root, variant)
    with chroot_mounts(root):
        if variant != "cli":
            chroot(root, ["/usr/bin/locale-gen"])
        chroot(root, ["/usr/bin/systemctl", "enable", "sshd", "NetworkManager", "systemd-resolved",
                      "systemd-timesyncd", "serial-getty@ttyAS0.service", "a7z-firstboot.service",
                      "a7z-grow-root.service"])
        chroot(root, ["/usr/bin/systemctl", "disable", "systemd-networkd.service", "systemd-networkd.socket"],
               stdout=subprocess.DEVNULL)
        # Retain the documented ALARM seed user for initial bring-up; no password is logged.
        password = os.environ.get("A7Z_IMAGE_PASSWORD", "alarm")
        if "\n" in password or ":" in password:
            raise ValueError("Image password cannot contain newline or colon")
        subprocess.run(["chroot", str(root), "/usr/bin/chpasswd"], input=f"alarm:{password}\n",
                       text=True, check=True)
        chroot(root, ["/usr/bin/usermod", "-aG", "wheel,video,render", "alarm"])
        chroot(root, ["/usr/bin/usermod", "-L", "root"])
        if variant != "cli":
            manager = "sddm" if variant == "kde" else "lightdm"
            selector = ["/usr/bin/a7z-gpu-desktop", "enable", "arch-glamor"]
            if manager == "sddm":
                selector += ["--display-manager", "sddm"]
            chroot(root, selector)
            chroot(root, ["/usr/bin/systemctl", "enable", manager])
            chroot(root, ["/usr/bin/systemctl", "set-default", "graphical.target"])
        else:
            chroot(root, ["/usr/bin/systemctl", "set-default", "multi-user.target"])
    (root / "etc/hostname").write_text("a7z-arch\n")
    (root / "etc/a7z").mkdir(exist_ok=True)
    (root / IMAGE_VARIANT).write_text(variant + "\n")
    (root / "etc/a7z/auto-grow-root").write_text("Expand only the final root partition on first boot.\n")
    kernel_config = root / "boot/config-6.6.98-4-aw2511"
    if kernel_config.is_file() and "CONFIG_SECURITY_LANDLOCK=y" not in kernel_config.read_text():
        pacman_conf = root / "etc/pacman.conf"
        contents = pacman_conf.read_text()
        if "\nDisableSandboxFilesystem\n" not in contents:
            # The official T5 kernel omits Landlock. Keep download-user privilege
            # separation and syscall filtering; only the unsupported part is disabled.
            contents = contents.replace("[options]\n", "[options]\n"
                "# A7Z T5 kernel has no Landlock; retain the syscall download sandbox.\n"
                "DisableSandboxFilesystem\n", 1)
            pacman_conf.write_text(contents)
    if variant == "xfce":
        content = "[Seat:*]\ngreeter-session=lightdm-gtk-greeter\nuser-session=xfce\n"
        managed_configuration(root, "etc/lightdm/lightdm.conf.d/50-a7z-desktop.conf",
                              content, legacy_content=content)
    (root / "etc/machine-id").write_text("")
    resolver = root / "etc/resolv.conf"
    if resolver.exists() or resolver.is_symlink():
        resolver.unlink()
    resolver.symlink_to("/run/systemd/resolve/stub-resolv.conf")
    sudoers = root / "etc/sudoers.d/10-wheel"
    sudoers.parent.mkdir(exist_ok=True)
    sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
    sudoers.chmod(0o440)
    sshconf = root / "etc/ssh/sshd_config.d/10-a7z.conf"
    sshconf.parent.mkdir(exist_ok=True)
    sshconf.write_text("PermitRootLogin no\nPasswordAuthentication yes\n")
    for file in (root / "etc/ssh").glob("ssh_host_*"):
        if file.is_file() or file.is_symlink():
            file.unlink()
    for marker in root.glob(".a7z-*"):
        if marker.is_file():
            marker.unlink()
        elif marker.is_dir() and not list(marker.iterdir()):
            marker.rmdir()
    for directory in (root / "var/log", root / "tmp", root / "var/tmp"):
        if directory.is_dir():
            for entry in directory.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
    print("Finalized image rootfs; initial user alarm (change password after first login).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bootstrap", "install", "finalize"])
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--mirror", default="https://mirrors.tuna.tsinghua.edu.cn/archlinuxarm")
    parser.add_argument("--package-cache", type=Path)
    parser.add_argument("--package-dir", type=Path, action="append", default=[])
    parser.add_argument("--variant", choices=("cli", "xfce", "kde"), help="fresh rootfs profile; default cli")
    parser.add_argument("--desktop", action="store_true", help="legacy alias for --variant xfce")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run as root on a Linux build host")
    ensure_binfmt()
    if os.environ.get("A7Z_MOUNT_NAMESPACE") != "1":
        environment = dict(os.environ, A7Z_MOUNT_NAMESPACE="1")
        return subprocess.call(["unshare", "--mount", "--propagation", "private", sys.executable,
                                str(Path(__file__).resolve()), *sys.argv[1:]], env=environment)
    {"bootstrap": bootstrap, "install": install, "finalize": finalize}[args.action](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
