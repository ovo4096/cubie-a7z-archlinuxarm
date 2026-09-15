#!/usr/bin/env python3
"""Build audited A7Z T5/Arch Linux ARM SD and UFS images; XFCE is the default.

Runs on Linux as root. On Windows, dispatches to the Ubuntu WSL distribution
as root while keeping rootfs/work files on its native Linux filesystem.
The work directory must be new/empty, or owned by this tool with --resume.
There is no disk-writing, directory-deletion or automatic flashing operation.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
STAGES = ("fetch", "extract", "bootstrap", "packages", "install", "finalize", "sanitize", "images", "archive", "audit")
UNSAFE = {"/", "/root", "/home", "/usr", "/etc", "/var", "/tmp", "/mnt", "/media", "/boot", "/dev", "/proc", "/sys"}
AUDIT_DOCUMENTS = ("RELEASE.zh-CN.md", "RELEASE-HYGIENE.zh-CN.md", "WIFI-FIRSTBOOT.zh-CN.md",
                   "KDE.zh-CN.md", "ROLLING-UPGRADE.zh-CN.md", "INSTALL.zh-CN.md")


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def atomic_json(path, value):
    partial = path.with_name(path.name + ".new")
    with partial.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(path)


def run(*args, capture=False):
    print("+ " + shlex.join(map(str, args)), flush=True)
    result = subprocess.run(list(map(str, args)), check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def script(name, *args):
    return run(sys.executable, REPO / "tools" / name, *args)


def safe_directory(path, label):
    original = Path(path).absolute()
    if original.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = original.resolve()
    if str(resolved) in UNSAFE or resolved.is_relative_to("/dev") or resolved.is_relative_to("/proc") or resolved.is_relative_to("/sys"):
        raise ValueError(f"Unsafe {label}: {resolved}")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"{label} is not a directory: {resolved}")
    return resolved


def native_filesystem(path):
    existing = path
    while not existing.exists():
        existing = existing.parent
    fs = run("findmnt", "--noheadings", "--output", "FSTYPE", "--target", existing, capture=True)
    if fs not in ("ext4", "xfs", "btrfs", "ext3", "ext2"):
        raise ValueError(f"Work/rootfs must use a native Linux filesystem, found {fs!r}. Use /root/a7z-archlinux-work/build-xfce inside WSL")


def file_records(paths, base=None):
    result = []
    for path in sorted(set(map(Path, paths))):
        if not path.is_file() or path.is_symlink():
            continue
        result.append({"path": str(path.relative_to(base) if base else path),
                       "bytes": path.stat().st_size, "sha256": digest(path)})
    return result


def recipe_files():
    selected = []
    for directory in ("tools", "runtime", "gpu", "vpu", "desktop", "packages", "kernel"):
        for path in (REPO / directory).rglob("*"):
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts and "work" not in path.parts:
                if path.suffix not in (".pyc", ".deb", ".zst", ".gz", ".xz"):
                    selected.append(path)
    return selected


def seed_fingerprint(directory):
    if directory is None:
        return None
    result = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("Private config seed may contain only regular files/directories")
        if path.is_file():
            result.update(str(path.relative_to(directory)).encode() + b"\0")
            result.update(bytes.fromhex(digest(path)))
    return result.hexdigest()


def validate_archive_names(archive):
    # Check names without materializing payloads; GNU tar provides the actual
    # owner/mode/hardlink/xattr-aware extraction into a fresh, empty directory.
    with tarfile.open(archive, "r|*") as source:
        for member in source:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"Archive has an unsafe member name: {member.name!r}")
            if member.islnk():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or ".." in target.parts:
                    raise ValueError(f"Archive has an unsafe hardlink target: {member.linkname!r}")


def extract_empty(archive, target):
    if target.is_symlink():
        raise ValueError(f"Extraction target is a symlink: {target}")
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError(f"Extraction requires an empty directory: {target}. A partial extraction is retained for inspection; use a fresh work directory")
    validate_archive_names(archive)
    run("tar", "--extract", "--file", archive, "--directory", target,
        "--numeric-owner", "--same-owner", "--preserve-permissions", "--xattrs", "--xattrs-include=*", "--acls",
        "--delay-directory-restore")


def check_binfmt():
    # Register just the installed AArch64 handler after a WSL VM restart.
    from rootfs import ensure_binfmt
    ensure_binfmt()
    if platform.machine().lower() in ("aarch64", "arm64"):
        return
    handler = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")
    if not handler.is_file():
        raise ValueError("AArch64 binfmt handler is missing. Install qemu-user-static/binfmt-support and enable qemu-aarch64")
    contents = handler.read_text()
    flags = re.search(r"^flags:\s*(\S+)", contents, re.M)
    if not contents.startswith("enabled\n") or not flags or "F" not in flags.group(1):
        raise ValueError("qemu-aarch64 binfmt must be enabled with the F (fix binary) flag for chroot")


def copy_verified(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or destination.is_symlink() or digest(destination) != digest(source):
            raise ValueError(f"Refusing different existing artifact: {destination}")
    else:
        with source.open("rb") as src, destination.open("xb") as out:
            shutil.copyfileobj(src, out, 8 * 1024 * 1024)


def runtime_configuration(root):
    """Audit the selected graphics/pacman configuration without reading credentials."""
    desktop = []
    for directory, suffix in (("etc/lightdm/lightdm.conf.d", ".conf"), ("etc/X11/xorg.conf.d", ".conf"),
                              ("etc/sddm.conf.d", ".conf")):
        for path in sorted((root / directory).glob("*" + suffix)):
            for raw in path.read_text().splitlines():
                line = raw.strip()
                if line.startswith(("xserver-command=", "greeter-session=", "user-session=", 'Option "kmsdev"',
                                    'Option "AccelMethod"', 'Option "ShadowFB"', 'Option "AutoAddGPU"',
                                    'ServerPath=', 'DisplayServer=', 'Session=')):
                    desktop.append({"file": str(path.relative_to(root)), "setting": line})
    options = {}
    section = None
    config = root / "etc/pacman.conf"
    if config.is_file():
        for raw in config.read_text().splitlines():
            line = raw.partition("#")[0].strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section == "options" and line:
                key, separator, value = line.partition("=")
                options[key.strip()] = value.strip() if separator else True
    pacman = {"download_user": options.get("DownloadUser"),
              "disable_all_sandbox": "DisableSandbox" in options,
              "disable_filesystem_sandbox": "DisableSandboxFilesystem" in options,
              "disable_syscall_sandbox": "DisableSandboxSyscalls" in options}
    return {"desktop": desktop, "pacman": pacman}


def copy_audit_documents(output, replace=False):
    """Snapshot the fixed documentation set; no image/package path is accepted."""
    records = []
    for name in AUDIT_DOCUMENTS:
        source = REPO / name
        if not source.is_file():
            continue
        target = output / "docs" / name
        if target.is_symlink() or not target.resolve().is_relative_to(output.resolve()):
            raise ValueError(f"Unsafe documentation audit path: {target}")
        if replace and target.exists():
            if not target.is_file():
                raise ValueError(f"Documentation target is not a file: {target}")
            temporary = target.with_name(target.name + ".new")
            with temporary.open("xb") as handle:
                handle.write(source.read_bytes())
            temporary.replace(target)
        else:
            copy_verified(source, target)
        records.append(target)
    return records


class Build:
    def __init__(self, args):
        self.args = args
        self.work = safe_directory(args.work_dir, "work directory")
        native_filesystem(self.work)
        self.cache = safe_directory(args.cache, "source cache")
        self.lock_path = Path(args.lock).resolve(strict=True)
        self.lock = json.loads(self.lock_path.read_text())
        self.hdmi_kernel_input = Path(args.hdmi_kernel_input).resolve(strict=True)
        if not self.hdmi_kernel_input.is_dir():
            raise ValueError("--hdmi-kernel-input must be the prepared HDMI kernel input directory")
        if any(not (self.hdmi_kernel_input / name).is_file() or (self.hdmi_kernel_input / name).is_symlink()
               for name in ("Image", "config", "System.map", "provenance.json")):
            raise ValueError("HDMI kernel input requires regular Image, config, System.map and provenance.json files")
        self.hdmi_kernel_records = file_records(
            [self.hdmi_kernel_input / name for name in ("Image", "config", "System.map", "provenance.json")],
            self.hdmi_kernel_input)
        self.seed = Path(args.config_dir).resolve(strict=True) if args.config_dir else None
        if self.seed and not self.seed.is_dir():
            raise ValueError("--config-dir is not a directory")
        self.root = self.work / "rootfs"
        self.vendor = self.work / "vendor/t5"
        self.packages = self.work / "packages"
        self.output = self.work / "output"
        self.pkgcache = self.work / "cache/pacman"
        self.state_file = self.work / ".a7z-build.json"
        self.epoch = int(self.lock["source_date_epoch"])
        self.recipes = file_records(recipe_files(), REPO)
        self.spec = {"source_lock_sha256": digest(self.lock_path), "variant": args.variant,
                     "hdmi_kernel_inputs": self.hdmi_kernel_records,
                     "mirror": args.mirror, "root_size_mib": args.root_size_mib,
                     "private_seed_sha256": seed_fingerprint(self.seed),
                     "password_source": "environment" if os.environ.get("A7Z_IMAGE_PASSWORD") else "rootfs-seed-default",
                     "recipes": self.recipes}
        if args.plan:
            return
        if self.work.exists() and any(self.work.iterdir()):
            if not args.resume or not self.state_file.is_file():
                raise ValueError("Work directory is not empty. --resume/--reuse accepts only a directory already managed by this builder")
            self.state = json.loads(self.state_file.read_text())
            if self.state.get("schema") != 1 or self.state.get("work_dir") != str(self.work) or self.state.get("spec") != self.spec:
                raise ValueError("Resume settings/source lock/recipes/seed differ from the saved build. Use a fresh work directory")
        else:
            self.work.mkdir(parents=True, exist_ok=True)
            self.state = {"schema": 1, "work_dir": str(self.work), "spec": self.spec,
                          "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "completed": {}}
            atomic_json(self.state_file, self.state)
        for directory in (self.output, self.packages, self.pkgcache):
            directory.mkdir(parents=True, exist_ok=True)
        os.environ["SOURCE_DATE_EPOCH"] = str(self.epoch)

    def checkpoint(self, stage, artifacts=()):
        self.state["completed"][stage] = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                            "artifacts": file_records(artifacts)}
        atomic_json(self.state_file, self.state)

    def stage_done(self, stage):
        record = self.state["completed"].get(stage)
        if record is None:
            return False
        for artifact in record["artifacts"]:
            path = Path(artifact["path"])
            if not path.is_file() or path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
                raise ValueError(f"Completed stage artifact changed or disappeared: {path}")
        print(f"Resume: verified completed stage {stage}", flush=True)
        return True

    def role(self, role):
        matches = [item for item in self.lock["artifacts"] if item["role"] == role]
        if len(matches) != 1:
            raise ValueError(f"Expected one locked {role} input")
        return matches[0]

    def fetch(self):
        script("sources.py", "verify" if self.args.offline else "fetch", "--lock", self.lock_path, "--cache", self.cache)
        copy_verified(self.lock_path, self.output / "sources.lock.json")
        for item in self.lock["artifacts"]:
            if item["role"] == "vendor-metadata":
                copy_verified(self.cache / item["name"], self.output / "upstream" / item["name"])
        return [self.output / "sources.lock.json", *(self.output / "upstream").glob("*")]

    def extract(self):
        outputs = []
        for role, directory in (("vendor-rootfs", self.vendor), ("arch-rootfs", self.root)):
            item = self.role(role)
            marker = directory.with_name(directory.name + ".source.json")
            # Each extraction gets its own checkpoint because the other large archive may fail later.
            if marker.is_file() and self.args.resume:
                if json.loads(marker.read_text()) != item or not directory.is_dir():
                    raise ValueError(f"Source extraction marker does not match: {marker}")
            else:
                extract_empty(self.cache / item["name"], directory)
                atomic_json(marker, item)
            outputs.append(marker)
        run("chroot", self.root, "/usr/bin/true")
        return outputs

    def bootstrap(self):
        args = ["bootstrap", "--rootfs", self.root, "--mirror", self.args.mirror, "--package-cache", self.pkgcache]
        args.extend(("--variant", self.args.variant))
        script("rootfs.py", *args)
        return []

    def package_payloads(self):
        script("package_bsp.py", "--vendor-root", self.vendor, "--output", self.packages / "bsp",
               "--source-date-epoch", self.epoch, "--hdmi-kernel-input", self.hdmi_kernel_input)
        gpu_args = ["--vendor-root", self.vendor, "--target-root", self.root,
                    "--strict", "--output", self.packages / "gpu", "--epoch", self.epoch]
        if self.args.variant == "cli":
            gpu_args.extend(("--components", "userspace"))
        script("package_gpu.py", *gpu_args)
        if self.args.variant != "cli":
            script("package_vpu.py", "--vendor-root", self.vendor, "--output", self.packages / "vpu")
        script("package_base.py", "--output", self.packages / "base", "--source-date-epoch", self.epoch)
        return [path for path in self.packages.rglob("*") if path.is_file()]

    def install(self):
        selected = self.packages / "install"
        selected.mkdir(exist_ok=True)
        archives = [*(self.packages / "bsp").glob("*.pkg.tar.zst"),
                    *(self.packages / "base").glob("*.pkg.tar.zst"),
                    *(self.packages / "gpu").glob("radxa-a7z-gpu-userspace-*.pkg.tar.zst")]
        if len(archives) < 7:
            raise ValueError("Expected five BSP packages, base, and private GPU userspace")
        if self.args.variant != "cli":
            vpu = list((self.packages / "vpu").glob("radxa-a7z-vpu-*.pkg.tar.zst"))
            if len(vpu) != 1:
                raise ValueError("Desktop image requires exactly one matching VPU package")
            archives.extend(vpu)
        for archive in archives:
            copy_verified(archive, selected / archive.name)
        if {path.name for path in selected.glob("*.pkg.tar.zst")} != {path.name for path in archives}:
            raise ValueError("Install staging contains an unexpected package")
        script("rootfs.py", "install", "--rootfs", self.root, "--package-cache", self.pkgcache,
               "--package-dir", selected)
        return []

    def finalize(self):
        args = ["finalize", "--rootfs", self.root]
        args.extend(("--variant", self.args.variant))
        script("rootfs.py", *args)
        # Generic roots must not contain machine-specific connection profiles or keys.
        profiles = self.root / "etc/NetworkManager/system-connections"
        keys = self.root / "home/alarm/.ssh/authorized_keys"
        if (profiles.is_dir() and any(profiles.iterdir())) or (keys.is_file() and keys.stat().st_size):
            raise ValueError("Prepared generic rootfs contains Wi-Fi profiles or authorized keys; keep private credentials only in --config-dir")
        for directory in (self.root / "boot/extlinux", self.root / "usr/lib/u-boot/radxa-a733"):
            if not directory.is_dir():
                raise ValueError(f"Prepared rootfs lacks required boot directory: {directory}")
        if self.args.variant == "xfce":
            observed = {entry["setting"] for entry in runtime_configuration(self.root)["desktop"]}
            required = {'Option "AccelMethod" "glamor"',
                        'Option "kmsdev" "/dev/dri/by-path/platform-soc@3000000:sunxi-drm-card"',
                        'Option "AutoAddGPU" "false"',
                        "xserver-command=/usr/lib/radxa-a7z-gpu/arch-Xorg -core"}
            if not required.issubset(observed):
                raise ValueError("XFCE finalization did not select the validated Arch glamor/KMS configuration")
        return []

    def sanitize(self):
        report = self.output / "rootfs-hygiene.json"
        script("sanitize.py", "--rootfs", self.root, "--apply", "--report", report)
        return [report]

    def image_paths(self):
        prefix = f"cubie-a7z-archlinuxarm-{self.args.variant}-t5" + ("-private" if self.seed else "")
        return [(512, self.output / f"{prefix}-sd-512.img"), (4096, self.output / f"{prefix}-ufs-4096.img")]

    def images(self):
        artifacts = []
        for sector, image in self.image_paths():
            metadata = Path(str(image) + ".json")
            sha = Path(str(image) + ".sha256")
            if image.exists():
                if not self.args.resume or not metadata.is_file() or not sha.is_file():
                    raise ValueError(f"Image output already exists without a complete resumable result: {image}")
                record = json.loads(metadata.read_text())
                if record["sector_size"] != sector or digest(image) != record["sha256"]:
                    raise ValueError(f"Existing image failed resume verification: {image}")
            else:
                args = ["build", "--rootfs", self.root, "--output", image, "--sector-size", sector]
                if self.args.root_size_mib:
                    args.extend(("--root-size-mib", self.args.root_size_mib))
                if self.seed:
                    args.extend(("--config-dir", self.seed))
                script("image.py", *args)
            artifacts.extend((image, metadata, sha))
        roots = [json.loads(Path(str(image) + ".json").read_text())["filesystem_uuids"]["rootfs"] for _, image in self.image_paths()]
        if len(set(roots)) != 2:
            raise ValueError("SD and UFS root UUIDs must differ")
        return artifacts

    def archive(self):
        artifacts = []
        for _, image in self.image_paths():
            compressed = Path(str(image) + ".zst")
            if not compressed.exists():
                run("zstd", f"-T{self.args.jobs}", "-10", "--check", "--no-progress", image, "-o", compressed)
            elif not self.args.resume:
                raise ValueError(f"Compressed image already exists: {compressed}")
            # Decompress and hash to prove the compressed artifact belongs to this raw image.
            process = subprocess.Popen(["zstd", "-dc", str(compressed)], stdout=subprocess.PIPE)
            checksum = hashlib.sha256()
            for chunk in iter(lambda: process.stdout.read(8 * 1024 * 1024), b""):
                checksum.update(chunk)
            process.stdout.close()
            if process.wait() or checksum.hexdigest() != json.loads(Path(str(image) + ".json").read_text())["sha256"]:
                raise ValueError(f"Compressed image integrity/content verification failed: {compressed}")
            artifacts.append(compressed)
        for folder in ("bsp", "gpu", "base", "vpu"):
            for source in sorted((self.packages / folder).glob("*")):
                if source.is_file():
                    destination = self.output / "packages" / source.name
                    copy_verified(source, destination)
                    artifacts.append(destination)
        return artifacts

    def audit(self):
        copy_audit_documents(self.output)
        copy_verified(self.root / "var/lib/a7z-package-snapshot.txt", self.output / "pacman-packages.txt")
        atomic_json(self.output / "pacman-cache-sha256.json", file_records(self.pkgcache.rglob("*"), self.pkgcache))
        atomic_json(self.output / "build-recipes-sha256.json", self.recipes)
        host = {"uname": run("uname", "-a", capture=True), "python": sys.version,
                "tar": run("tar", "--version", capture=True).splitlines()[0],
                "sfdisk": run("sfdisk", "--version", capture=True),
                "zstd": run("zstd", "--version", capture=True)}
        outputs = file_records((path for path in self.output.rglob("*")
                                if path.name not in ("build-manifest.json", "SHA256SUMS")), self.output)
        manifest = {"schema": 1, "board": "radxa-cubie-a7z", "vendor_release": self.lock["vendor_release"],
                    "kernel_release": self.lock["kernel_release"], "variant": self.args.variant,
                    "desktop": {"xfce": "XFCE + LightDM + Arch Xorg glamor using private T5 EGL/GBM",
                                "kde": "Plasma X11 + SDDM + Arch Xorg glamor using private T5 EGL/GBM",
                                "cli": None}[self.args.variant],
                    "runtime_configuration": runtime_configuration(self.root),
                    "private_seed_included": self.seed is not None,
                    "source_lock_sha256": digest(self.lock_path), "source_date_epoch": self.epoch,
                    "started_at": self.state["started_at"], "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "host": host, "artifacts": outputs,
                    "hardware_validation": "Not asserted by the image builder; see separately maintained board test records",
                    "rebuild_limit": "Rootfs/BSP inputs are hash-locked. pacman -Syu uses a rolling mirror; package snapshot and cached archive hashes audit this run, but do not establish a bit-for-bit reproducible future rebuild. Image UUIDs are generated separately per medium.",
                    "gpu_default": ("Arch Xorg is launched with private T5 EGL/GBM for glamor. Mesa/libglvnd and login-session environment remain Arch-provided; vendor Xorg is not enabled. GLX/AIGLX remains a software path."
                                    if self.args.variant != "cli" else "Private userspace is installed for explicit EGL/GLES/Vulkan diagnostics; no desktop is selected."),
                    "graphics_validation_limit": "EGL/GLES pixel rendering and Vulkan device enumeration were demonstrated on the validation board; these checks do not cover arbitrary GLX clients or Vulkan rendering workloads."}
        atomic_json(self.output / "build-manifest.json", manifest)
        checksums = file_records((path for path in self.output.rglob("*") if path.name != "SHA256SUMS"), self.output)
        (self.output / "SHA256SUMS").write_text("".join(f"{record['sha256']}  {record['path']}\n" for record in checksums))
        return [self.output / "build-manifest.json", self.output / "SHA256SUMS", self.output / "pacman-packages.txt",
                self.output / "pacman-cache-sha256.json", self.output / "build-recipes-sha256.json"]

    def run(self):
        if self.args.plan:
            print(json.dumps({"work_dir": str(self.work), "source_cache": str(self.cache), "rootfs": str(self.root),
                              "vendor_rootfs": str(self.vendor), "output": str(self.output), "variant": self.args.variant,
                              "private_seed_included": self.seed is not None, "stages": STAGES,
                              "images": [str(path) for _, path in self.image_paths()],
                              "no_real_disks_written": True}, indent=2))
            return
        actions = {"fetch": self.fetch, "extract": self.extract, "bootstrap": self.bootstrap,
                   "packages": self.package_payloads, "install": self.install, "finalize": self.finalize, "sanitize": self.sanitize,
                   "images": self.images, "archive": self.archive, "audit": self.audit}
        for stage in STAGES:
            if not self.stage_done(stage):
                self.checkpoint(stage, actions[stage]())
            elif stage == "fetch":
                # Recheck retained upstream archives even when an extraction checkpoint already exists.
                script("sources.py", "verify", "--lock", self.lock_path, "--cache", self.cache)
            if self.args.stop_after == stage:
                print(f"Stopped after {stage}. Continue with identical arguments plus --resume (and without --stop-after).")
                return
        print(f"Build completed: {self.output}\nCheck SHA256SUMS before flashing. No physical disk was written.")


def windows_dispatch(argv, distribution):
    wsl_script = subprocess.check_output(["wsl.exe", "-d", distribution, "-u", "root", "--exec", "wslpath", "-a", Path(__file__).resolve().as_posix()], text=True).strip()
    forwarded = list(argv)
    for index, value in enumerate(forwarded):
        if re.match(r"^[A-Za-z]:[\\/]", value):
            forwarded[index] = subprocess.check_output(["wsl.exe", "-d", distribution, "-u", "root", "--exec", "wslpath", "-a", value.replace("\\", "/")], text=True).strip()
    environment = dict(os.environ)
    if "A7Z_IMAGE_PASSWORD" in environment:
        entries = [entry for entry in environment.get("WSLENV", "").split(":") if entry]
        if not any(entry.split("/")[0] == "A7Z_IMAGE_PASSWORD" for entry in entries):
            entries.append("A7Z_IMAGE_PASSWORD/u")
        environment["WSLENV"] = ":".join(entries)
    return subprocess.call(["wsl.exe", "-d", distribution, "-u", "root", "--exec", "python3", wsl_script, *forwarded], env=environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default="/root/a7z-archlinux-work/build-xfce")
    parser.add_argument("--cache", default=str(REPO / ".cache/upstream"))
    parser.add_argument("--lock", default=str(REPO / "config/sources.lock.json"))
    parser.add_argument("--hdmi-kernel-input", required=True,
                        help="HDMI kernel input prepared by tools/build_hdmi_kernel.py or extracted from the matching release bundle")
    parser.add_argument("--variant", choices=("xfce", "cli", "kde"), default="xfce")
    parser.add_argument("--mirror", default="https://mirrors.tuna.tsinghua.edu.cn/archlinuxarm")
    parser.add_argument("--config-dir", help="optional private seed; never copied into the generic rootfs")
    parser.add_argument("--root-size-mib", type=int, help="root partition size; otherwise image.py estimates it")
    parser.add_argument("--resume", "--reuse", action="store_true", help="resume only a matching builder-owned directory")
    parser.add_argument("--offline-inputs", "--offline", dest="offline", action="store_true", help="verify cached locked inputs; pacman still requires its configured mirror")
    parser.add_argument("--stop-after", choices=STAGES)
    parser.add_argument("--plan", action="store_true", help="print paths/stages without creating a build or downloading")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="zstd worker count")
    parser.add_argument("--wsl-distribution", default="Ubuntu", help="Windows dispatcher distribution")
    args = parser.parse_args()
    if sys.platform == "win32":
        return windows_dispatch(sys.argv[1:], args.wsl_distribution)
    try:
        if sys.platform != "linux" or (not args.plan and os.geteuid() != 0):
            raise ValueError("Build requires Linux root privileges; on Windows install WSL2 Ubuntu")
        if not 1 <= args.jobs <= 64 or (args.root_size_mib is not None and args.root_size_mib < 256):
            raise ValueError("jobs must be 1..64; root-size-mib must be at least 256")
        if "A7Z_IMAGE_PASSWORD" in os.environ:
            password = os.environ["A7Z_IMAGE_PASSWORD"]
            if not password or "\n" in password or ":" in password:
                raise ValueError("A7Z_IMAGE_PASSWORD must be nonempty and contain no newline or colon")
        if not args.plan:
            commands = ("findmnt", "tar", "chroot", "unshare", "mount", "umount", "losetup", "sfdisk", "blockdev",
                        "rsync", "mkfs.fat", "mkfs.ext4", "e2fsck", "readelf", "patchelf", "bsdtar", "zstd",
                        "make", "patch", "gcc", "g++", "modinfo")
            compiler_prefix = "" if os.uname().machine.lower() in ("aarch64", "arm64") else "aarch64-linux-gnu-"
            commands += tuple(compiler_prefix + name for name in ("gcc", "ld", "nm", "objcopy", "objdump"))
            missing = [command for command in commands if not shutil.which(command)]
            if missing:
                raise ValueError("Missing Linux build tools: " + ", ".join(missing))
            check_binfmt()
        Build(args).run()
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Build refused/failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
