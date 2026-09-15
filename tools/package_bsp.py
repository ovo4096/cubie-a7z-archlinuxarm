#!/usr/bin/env python3
"""Package the locked T5 BSP with a source-built PowerVR fdinfo fix.

Run on Linux against an extracted, unmodified T5 rootfs. See
gpu/kernel/README.md for the module rebuild. Other BSP payloads remain vendor
binaries with per-file provenance.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile

KERNEL = "6.6.98-4-aw2511"
RELEASE_URL = "https://github.com/radxa-build/radxa-a733/releases/tag/rsdk-t5"
LOCKED = {
    f"linux-image-{KERNEL}": "6.6.98-4",
    "u-boot-dlan17": "2026.04-3",
    "u-boot-radxa-a733": "2026.04-3",
    "aic8800-usb-dkms": "5.0+git20260123.5f7be68d-7",
    "aic8800-firmware": "5.0+git20260123.5f7be68d-7",
    "radxa-firmware": "0.2.39",
    "radxa-overlays-dkms": "0.2.28",
    "radxa-system-config-aic8800-usb-dkms": "0.7.3",
    "img-bxm-dkms": "0.1.0-3",
    "xserver-xorg-img-bxm-1.21.1-2.deb": "1.0.1",
}
SPECS = {
    "linux-radxa-a7z": {
        "version": "6.6.98_4-1", "description": "Radxa A7Z T5 Linux kernel, device trees and in-tree modules",
        "depends": ["coreutils", "kmod"], "provides": ["linux=6.6.98", "linux-radxa-a7z-kernel=6.6.98_4_aw2511"],
        "conflicts": ["linux-aarch64"], "licenses": ["GPL-2.0-only"],
    },
    "radxa-a7z-bootloader": {
        "version": "2026.04_3-1", "description": "Radxa A7Z T5 U-Boot binary and vendor setup script (installation does not flash storage)",
        "depends": ["bash", "coreutils", "util-linux"], "licenses": ["GPL-2.0-or-later", "LicenseRef-vendor-firmware"],
    },
    "radxa-a7z-firmware": {
        "version": "0.2.39-1", "description": "Locked Radxa T5, AIC8800 and PowerVR firmware",
        "licenses": ["LicenseRef-vendor-firmware"],
    },
    "radxa-a7z-wireless": {
        "version": "5.0+git20260123.5f7be68d_7-1", "description": "T5 AIC8800 USB wireless modules prebuilt for the A7Z kernel",
        "depends": ["linux-radxa-a7z=6.6.98_4-1", "radxa-a7z-firmware", "kmod"], "licenses": ["GPL-2.0-only"],
    },
    "radxa-a7z-gpu-kmod": {
        "version": "0.1.0_3-3", "description": "T5 PowerVR kernel module rebuilt with the DRM fdinfo fix for the A7Z kernel",
        "depends": ["linux-radxa-a7z=6.6.98_4-1", "radxa-a7z-firmware", "kmod"], "licenses": ["GPL-2.0-only", "MIT"],
    },
}
MODULE_RE = re.compile(r"\.ko(?:\.(?:gz|xz|zst))?$")
GPU_FIX_PROVENANCE = "usr/share/radxa-a7z-gpu-kmod/fdinfo-fix-provenance.json"


def build_fixed_module(vendor_root: Path, source_date_epoch: int, jobs: int = 2) -> tuple[bytes, dict]:
    # Lazy import keeps unrelated metadata checks usable without invoking or
    # loading the compiler. The CLI's script directory contains this helper.
    from build_gpu_kmod import build_fixed_module as compile_module
    return compile_module(vendor_root, source_date_epoch, jobs=jobs)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def parse_status(path: Path) -> dict[str, dict[str, str]]:
    result = {}
    for paragraph in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
        fields: dict[str, str] = {}
        current = None
        for line in paragraph.splitlines():
            if line.startswith((" ", "\t")) and current:
                fields[current] += "\n" + line[1:]
            elif ": " in line:
                current, value = line.split(": ", 1)
                fields[current] = value
        if fields.get("Status") == "install ok installed":
            result[fields["Package"]] = fields
    return result


def clean_path(value: str) -> str:
    if "\x00" in value or "\n" in value:
        raise ValueError(f"Unsafe pathname: {value!r}")
    parts = PurePosixPath(value.lstrip("/")).parts
    if ".." in parts:
        raise ValueError(f"Traversal pathname: {value!r}")
    return "/".join(part for part in parts if part != ".")


def arch_path(value: str) -> str:
    value = clean_path(value)
    for old, new in (("usr/sbin", "usr/bin"), ("sbin", "usr/bin"), ("bin", "usr/bin"), ("lib64", "usr/lib"), ("lib", "usr/lib")):
        if value == old or value.startswith(old + "/"):
            return new + value[len(old):]
    return value


def vendor_path(root: Path, name: str, follow_final: bool = False) -> Path:
    """Resolve rootfs absolute symlinks inside root, never against the host /usr."""
    pending = list(PurePosixPath(clean_path(name)).parts)
    resolved: list[str] = []
    links = 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved:
                raise ValueError(f"Symlink escapes rootfs: {name}")
            resolved.pop()
            continue
        candidate = root.joinpath(*resolved, part)
        if candidate.is_symlink() and (pending or follow_final):
            links += 1
            if links > 40:
                raise ValueError(f"Symlink loop: {name}")
            target = os.readlink(candidate)
            if target.startswith("/"):
                resolved = []
            pending = list(PurePosixPath(target).parts) + pending
            if pending and pending[0] == "/":
                pending.pop(0)
        else:
            resolved.append(part)
    return root.joinpath(*resolved)


def normalized_link(source_name: str, destination: str, target: str) -> str:
    virtual = posixpath.normpath(target if target.startswith("/") else posixpath.join("/", posixpath.dirname(source_name.lstrip("/")), target))
    mapped = arch_path(virtual)
    return "/" + mapped if target.startswith("/") else posixpath.relpath(mapped, posixpath.dirname(destination))


def elf_modinfo(data: bytes) -> dict[str, str]:
    """Read the ELF .modinfo section, not lookalike strings in other sections."""
    if data[:6] != b"\x7fELF\x02\x01" or int.from_bytes(data[18:20], "little") != 183:
        raise ValueError("Not a little-endian ELF64 AArch64 module")
    try:
        section_offset = struct.unpack_from("<Q", data, 40)[0]
        entry_size, count, strings_index = struct.unpack_from("<HHH", data, 58)
        if entry_size < 64 or strings_index >= count or section_offset + count * entry_size > len(data):
            raise ValueError("Invalid ELF section table")
        def section(index):
            offset = section_offset + index * entry_size
            name, section_type = struct.unpack_from("<II", data, offset)
            if section_type == 8:  # SHT_NOBITS (.bss) has no file bytes.
                return name, b""
            start, length = struct.unpack_from("<QQ", data, offset + 24)
            if start + length > len(data):
                raise ValueError("ELF section exceeds file")
            return name, data[start:start + length]
        _, strings = section(strings_index)
        for index in range(count):
            name, body = section(index)
            if strings[name:].split(b"\0", 1)[0] == b".modinfo":
                result = {}
                for value in body.split(b"\0"):
                    if b"=" in value:
                        key, text = value.split(b"=", 1)
                        result[key.decode("ascii")] = text.decode("utf-8")
                return result
    except (struct.error, UnicodeDecodeError) as error:
        raise ValueError(f"Invalid ELF module metadata: {error}") from error
    raise ValueError("ELF .modinfo section missing")


class Builder:
    def __init__(self, root: Path, output: Path, epoch: int):
        self.root, self.output, self.epoch = root.resolve(), output.resolve(), epoch
        self.status_path = self.root / "var/lib/dpkg/status"
        self.status = parse_status(self.status_path)
        for name, version in LOCKED.items():
            actual = self.status.get(name, {}).get("Version")
            if actual != version:
                raise ValueError(f"T5 source mismatch: {name}: expected {version}, found {actual!r}")
        self.entries: dict[str, dict[str, dict]] = {name: {} for name in SPECS}
        self.sources: dict[str, set[str]] = {name: set() for name in SPECS}
        self.module_info: list[dict] = []
        self.warnings: list[str] = []
        self.exclusions: list[dict] = []
        self.gpu_module_rebuild: dict | None = None

    def paths(self, package: str) -> list[str]:
        info = self.root / "var/lib/dpkg/info"
        exact = info / (package + ".list")
        candidates = [exact] if exact.exists() else list(info.glob(package + ":*.list"))
        if len(candidates) != 1:
            raise ValueError(f"Need one dpkg file list for {package}, got {candidates}")
        return [clean_path(line) for line in candidates[0].read_text().splitlines() if line not in ("/.", "/")]

    def add(self, package: str, source_name: str, source_package: str, destination: str | None = None, dereference: bool = False) -> None:
        source_name = clean_path(source_name)
        destination = arch_path(destination or source_name)
        source = vendor_path(self.root, source_name, follow_final=dereference)
        if not source.exists() and not source.is_symlink():
            raise ValueError(f"Missing source payload: {source_name} ({source_package})")
        st = source.lstat()
        if stat.S_ISDIR(st.st_mode):
            return
        entry: dict = {"source_path": source_name, "source_package": source_package, "mode": stat.S_IMODE(st.st_mode), "source": source}
        if stat.S_ISLNK(st.st_mode):
            entry.update(type="symlink", target=normalized_link(source_name, destination, os.readlink(source)), size=0)
        elif stat.S_ISREG(st.st_mode):
            entry.update(type="file", size=st.st_size, sha256=digest_file(source))
        else:
            raise ValueError(f"Special files are not accepted: {source_name}")
        old = self.entries[package].get(destination)
        if old and self.public_entry(old) != self.public_entry(entry):
            raise ValueError(f"Conflicting payload at {destination}")
        self.entries[package][destination] = entry
        self.sources[package].add(source_package)

    @staticmethod
    def public_entry(entry: dict) -> dict:
        return {key: value for key, value in entry.items() if key not in ("source", "data")}

    def generated(self, package: str, destination: str, data: bytes | None = None, target: str | None = None) -> None:
        entry: dict = {"source_package": "a7z-archlinux-port", "mode": 0o644}
        if target is not None:
            entry.update(type="symlink", mode=0o777, target=target, size=0)
        else:
            assert data is not None
            entry.update(type="file", size=len(data), sha256=sha256(data), data=data)
        if destination in self.entries[package]:
            raise ValueError(f"Generated file would overwrite payload: {destination}")
        self.entries[package][destination] = entry

    def walk_files(self, root_name: str):
        start = vendor_path(self.root, root_name, follow_final=True)
        if not start.is_dir():
            raise ValueError(f"Missing directory: {root_name}")
        for directory, dirs, files in os.walk(start, followlinks=False):
            dirs.sort()
            for name in sorted(files + [name for name in dirs if (Path(directory) / name).is_symlink()]):
                path = Path(directory) / name
                yield str(PurePosixPath(root_name) / path.relative_to(start).as_posix())

    def module(self, name: str) -> None:
        source = vendor_path(self.root, name, follow_final=True)
        data = source.read_bytes()
        if name.endswith(".xz"):
            data = lzma.decompress(data)
        elif name.endswith(".gz"):
            data = gzip.decompress(data)
        elif name.endswith(".zst"):
            data = subprocess.check_output(["zstd", "-q", "-d", "-c", str(source)])
        metadata = elf_modinfo(data)
        vermagic, module_name = metadata.get("vermagic", ""), metadata.get("name", "")
        if vermagic.split(" ")[0] != KERNEL:
            raise ValueError(f"Module ABI mismatch: {name}: {vermagic!r}")
        basename = PurePosixPath(name).name
        if basename.startswith("radxa-overlays.ko"):
            self.exclusions.append({"path": arch_path(name), "reason": "Vendor dummy module only triggers DKMS overlay compilation; compiled DTBO files are packaged directly", "vermagic": vermagic})
            return
        if basename.startswith("aic"):
            package, deb = "radxa-a7z-wireless", "aic8800-usb-dkms"
        elif basename.startswith(("pvrsrvkm", "pvr_")):
            package, deb = "radxa-a7z-gpu-kmod", "img-bxm-dkms"
        elif "/updates/" in name or "/extra/" in name:
            raise ValueError(f"Unclassified external module (review required): {name}")
        else:
            package, deb = "linux-radxa-a7z", f"linux-image-{KERNEL}"
        self.add(package, name, deb)
        self.module_info.append({"path": arch_path(name), "package": package, "name": module_name, "vermagic": vermagic, "srcversion": metadata.get("srcversion", ""), "version": metadata.get("version", "")})

    def replace_gpu_module(self) -> None:
        """Replace only the selected pvrsrvkm payload; any failed gate aborts."""
        package = "radxa-a7z-gpu-kmod"
        identified = {record["path"] for record in self.module_info
                      if record["package"] == package and record["name"] == "pvrsrvkm"}
        candidates = [(path, entry) for path, entry in self.entries[package].items()
                      if path in identified or PurePosixPath(path).name.startswith("pvrsrvkm.ko")]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one original T5 pvrsrvkm module")
        path, original = candidates[0]
        if PurePosixPath(path).name != "pvrsrvkm.ko.xz" or original["type"] != "file":
            raise ValueError("The locked pvrsrvkm payload must be a regular .ko.xz file")
        source_payload = original["source"].read_bytes()
        if sha256(source_payload) != original["sha256"]:
            raise ValueError("Original pvrsrvkm payload changed after selection")
        source_elf = lzma.decompress(source_payload)
        source_info = elf_modinfo(source_elf)
        if source_info.get("name") != "pvrsrvkm":
            raise ValueError("Original T5 GPU module name is not pvrsrvkm")

        # The compiler owns a temporary native workspace outside package output.
        # There is deliberately no fallback to the vulnerable vendor binary.
        fixed_elf, compiler_report = build_fixed_module(self.root, self.epoch, jobs=2)
        if not isinstance(fixed_elf, bytes) or fixed_elf == source_elf:
            raise ValueError("GPU module rebuild did not return a changed ELF payload")
        fixed_info = elf_modinfo(fixed_elf)
        for key in ("name", "version", "vermagic"):
            if fixed_info.get(key, "") != source_info.get(key, ""):
                raise ValueError(f"Rebuilt GPU module ABI mismatch ({key}): {fixed_info.get(key)!r}")
        if fixed_info.get("vermagic", "").split(" ")[0] != KERNEL:
            raise ValueError("Rebuilt GPU module does not target the locked kernel")
        if (not isinstance(compiler_report, dict) or compiler_report.get("schema") != 1 or
                compiler_report.get("fix") != "generic-drm-fdinfo" or
                compiler_report.get("source_date_epoch") != self.epoch or
                compiler_report.get("original_module_path") != path or
                compiler_report.get("module_sha256") != sha256(fixed_elf) or
                compiler_report.get("original_module_sha256") != original["sha256"] or
                compiler_report.get("original_elf_sha256") != sha256(source_elf) or
                compiler_report.get("vermagic") != fixed_info["vermagic"]):
            raise ValueError("GPU compiler provenance does not match the selected and rebuilt payloads")
        compiler_report = json.loads(json_bytes(compiler_report))
        # Match T5 scripts/Makefile.modinst and its shipped module. The kernel
        # XZ decoder rejects CRC64 with XZ_OPTIONS_ERROR even though host-side
        # liblzma can decompress it successfully.
        fixed_payload = lzma.compress(
            fixed_elf, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32,
            filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20, "preset": 6}])
        provenance = {"schema": 1, "installed_path": path,
                      "source_path": original["source_path"], "source_package": original["source_package"],
                      "source_sha256": original["sha256"], "source_elf_sha256": sha256(source_elf),
                      "fixed_sha256": sha256(fixed_payload), "fixed_elf_sha256": sha256(fixed_elf),
                      "source_modinfo": source_info, "fixed_modinfo": fixed_info,
                      "compression": "xz, CRC32, LZMA2 dict=1MiB, preset 6", "build": compiler_report}
        replacement = {key: value for key, value in original.items() if key != "source"}
        replacement.update(data=fixed_payload, size=len(fixed_payload), sha256=sha256(fixed_payload),
                           source_sha256=original["sha256"], source_elf_sha256=sha256(source_elf),
                           fixed_sha256=sha256(fixed_payload), fixed_elf_sha256=sha256(fixed_elf),
                           transformation="source-build-with-generic-drm-fdinfo")
        self.generated(package, GPU_FIX_PROVENANCE, data=json_bytes(provenance))
        self.entries[package][path] = replacement
        self.gpu_module_rebuild = provenance
        for record in self.module_info:
            if record["package"] == package and record["path"] == path:
                record.update(source_srcversion=record["srcversion"],
                              srcversion=fixed_info.get("srcversion", ""), rebuilt=True)

    def select(self) -> None:
        linux_deb = f"linux-image-{KERNEL}"
        for name in self.paths(linux_deb):
            mapped = arch_path(name)
            if mapped.startswith(f"usr/lib/modules/{KERNEL}/"):
                continue
            if mapped.startswith((f"usr/lib/linux-image-{KERNEL}/", f"boot/dtbs/{KERNEL}/")) or mapped in {f"boot/{prefix}-{KERNEL}" for prefix in ("vmlinuz", "config", "System.map")}:
                self.add("linux-radxa-a7z", name, linux_deb)
        for name in self.walk_files(f"usr/lib/modules/{KERNEL}"):
            basename = PurePosixPath(name).name
            if MODULE_RE.search(name):
                self.module(name)
            elif basename in ("modules.builtin", "modules.builtin.modinfo", "modules.order"):
                self.add("linux-radxa-a7z", name, linux_deb)
        kernel_image = f"boot/vmlinuz-{KERNEL}"
        if kernel_image not in self.entries["linux-radxa-a7z"]:
            raise ValueError(f"Missing locked kernel image: {kernel_image}")
        with vendor_path(self.root, kernel_image, follow_final=True).open("rb") as stream:
            header = stream.read(64)
        if header[56:60] != b"ARMd":
            raise ValueError("T5 vmlinuz is not a raw ARM64 Image; refusing to guess boot image format")
        self.generated("linux-radxa-a7z", f"usr/lib/modules/{KERNEL}/vmlinuz", target=f"../../../../boot/vmlinuz-{KERNEL}")
        self.generated("linux-radxa-a7z", f"usr/lib/modules/{KERNEL}/pkgbase", data=b"linux-radxa-a7z\n")
        # A stable, namespaced Image path; generic /boot/Image remains runtime policy.
        self.generated("linux-radxa-a7z", "boot/Image-radxa-a7z", target=f"vmlinuz-{KERNEL}")
        for name in self.walk_files("boot/dtbo"):
            if name.endswith((".dtbo", ".dtbo.disabled")):
                self.add("linux-radxa-a7z", name, "radxa-overlays-dkms")

        for deb in ("u-boot-dlan17", "u-boot-radxa-a733"):
            for name in self.paths(deb):
                if arch_path(name).startswith("usr/lib/u-boot/"):
                    self.add("radxa-a7z-bootloader", name, deb)
        for deb in ("aic8800-firmware", "radxa-firmware", "img-bxm-dkms", "xserver-xorg-img-bxm-1.21.1-2.deb"):
            for name in self.paths(deb):
                if arch_path(name).startswith("usr/lib/firmware/"):
                    if deb == "radxa-firmware":
                        source = vendor_path(self.root, name)
                        if not source.is_dir():
                            self.exclusions.append({"path": arch_path(name), "source_package": deb, "reason": "Other-board/general firmware; A7Z uses AIC8800 and PowerVR payloads; preserve Arch linux-firmware ownership"})
                        continue
                    self.add("radxa-a7z-firmware", name, deb)
        # Only static module options and udev rules are eligible; Debian DKMS,
        # initramfs scripts, service presets and maintainer scripts are excluded.
        for deb in ("aic8800-usb-dkms", "radxa-system-config-aic8800-usb-dkms"):
            if deb not in self.status:
                continue
            for name in self.paths(deb):
                if arch_path(name).startswith(("etc/modprobe.d/", "usr/lib/modprobe.d/", "etc/modules-load.d/", "usr/lib/modules-load.d/", "usr/lib/udev/rules.d/", "etc/udev/rules.d/", "usr/lib/systemd/network/")):
                    self.add("radxa-a7z-wireless", name, deb)

        if not any("sun60i-a733-cubie-a7z.dtb" in name for name in self.entries["linux-radxa-a7z"]):
            raise ValueError("A7Z device tree is absent from selected kernel payload")
        if not any(name.endswith("u-boot-sunxi-with-spl.bin") for name in self.entries["radxa-a7z-bootloader"]):
            raise ValueError("T5 U-Boot/SPL binary is absent")
        for package in ("radxa-a7z-wireless", "radxa-a7z-gpu-kmod"):
            if not any(MODULE_RE.search(name) for name in self.entries[package]):
                raise ValueError(f"T5 prebuilt modules absent: {package}; compile against exact headers before repackaging")
        for firmware in ("rgx.fw.36.56.104.183", "rgx.sh.36.56.104.183"):
            if f"usr/lib/firmware/{firmware}" not in self.entries["radxa-a7z-firmware"]:
                raise ValueError(f"Matching PowerVR firmware missing: {firmware}")

        self.replace_gpu_module()

        for package in SPECS:
            for deb in sorted(self.sources[package].copy()):
                copyright_path = f"usr/share/doc/{deb}/copyright"
                source = vendor_path(self.root, copyright_path, follow_final=True)
                if source.is_file():
                    self.add(package, copyright_path, deb, destination=f"usr/share/licenses/{package}/{deb}/copyright", dereference=True)
                else:
                    self.warnings.append(f"No Debian copyright file supplied for {deb} in {package}; review redistribution terms before publishing")

        owners: dict[str, str] = {}
        for package, entries in self.entries.items():
            for path in entries:
                if path in owners:
                    raise ValueError(f"File owned by two BSP packages: {path}: {owners[path]}, {package}")
                owners[path] = package

    def provenance(self, package: str) -> dict:
        if package == "radxa-a7z-gpu-kmod" and self.gpu_module_rebuild is None:
            raise ValueError("GPU module cannot be packaged without the validated fdinfo rebuild")
        result = {
            "schema": 1, "package": package, "version": SPECS[package]["version"], "kernel_release": KERNEL,
            "vendor_release": RELEASE_URL, "source_date_epoch": self.epoch,
            "method": "binary-repackage; no Debian maintainer scripts executed; no storage flashed",
            "recipe_sha256": digest_file(Path(__file__)), "dpkg_status_sha256": digest_file(self.status_path),
            "source_packages": [{"name": name, "version": self.status[name]["Version"], "source": self.status[name].get("Source", name)} for name in sorted(self.sources[package])],
            "modules": [item for item in self.module_info if item["package"] == package],
            "files": {name: self.public_entry(entry) for name, entry in sorted(self.entries[package].items())},
        }
        if package == "radxa-a7z-gpu-kmod":
            result["method"] = "vendor BSP plus source-built PowerVR DRM fdinfo fix; no Debian maintainer scripts executed; no storage flashed"
            result["module_rebuild"] = self.gpu_module_rebuild
        return result

    def pkginfo(self, package: str, size: int) -> bytes:
        spec = SPECS[package]
        lines = ["# Generated by tools/package_bsp.py; see packaged BSP provenance", f"pkgname = {package}", f"pkgbase = {package}", f"pkgver = {spec['version']}", f"pkgdesc = {spec['description']}", f"url = {RELEASE_URL}", f"builddate = {self.epoch}", "packager = A7Z Arch Linux ARM port", f"size = {size}", "arch = aarch64"]
        for key, field in (("license", "licenses"), ("depend", "depends"), ("provides", "provides"), ("conflict", "conflicts")):
            lines.extend(f"{key} = {value}" for value in spec.get(field, []))
        return ("\n".join(lines) + "\n").encode()

    def archive(self, package: str) -> dict:
        provenance = self.provenance(package)
        provenance_name = f"usr/share/doc/{package}/bsp-provenance.json"
        self.generated(package, provenance_name, data=json_bytes(provenance))
        entries = dict(self.entries[package])
        for name in list(entries):
            for parent in PurePosixPath(name).parents:
                if str(parent) != ".":
                    entries.setdefault(str(parent), {"type": "directory", "mode": 0o755, "size": 0})
        size = sum(entry["size"] for entry in entries.values())
        info = self.pkginfo(package, size)
        entries[".PKGINFO"] = {"type": "file", "mode": 0o644, "size": len(info), "data": info, "sha256": sha256(info)}

        def escape(value: str) -> str:
            return "".join(f"\\{ord(char):03o}" if char in " \\#\t\n" else char for char in value)
        mtree = ["#mtree", f"/set uid=0 gid=0 time={self.epoch}"]
        for name, entry in sorted(entries.items()):
            kind = {"directory": "dir", "file": "file", "symlink": "link"}[entry["type"]]
            line = f"./{escape(name)} type={kind} mode={entry['mode']:o}"
            if kind == "file":
                line += f" size={entry['size']} sha256digest={entry['sha256']}"
            elif kind == "link":
                line += f" link={escape(entry['target'])}"
            mtree.append(line)
        mtree_bytes = gzip.compress(("\n".join(mtree) + "\n").encode(), compresslevel=9, mtime=0)
        entries[".MTREE"] = {"type": "file", "mode": 0o644, "size": len(mtree_bytes), "data": mtree_bytes}
        name = f"{package}-{SPECS[package]['version']}-aarch64.pkg.tar.zst"
        destination = self.output / name
        with tempfile.TemporaryDirectory(prefix="a7z-bsp-", dir=self.output) as tmp:
            tar_path = Path(tmp) / "package.tar"
            with tarfile.open(tar_path, "w", format=tarfile.GNU_FORMAT) as archive:
                for path in sorted(entries, key=lambda name: (not name.startswith("."), name)):
                    entry = entries[path]
                    info = tarfile.TarInfo(path + ("/" if entry["type"] == "directory" else ""))
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime, info.mode = self.epoch, entry["mode"]
                    if entry["type"] == "directory":
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    elif entry["type"] == "symlink":
                        info.type, info.linkname = tarfile.SYMTYPE, entry["target"]
                        archive.addfile(info)
                    else:
                        info.size = entry["size"]
                        if "data" in entry:
                            archive.addfile(info, io.BytesIO(entry["data"]))
                        else:
                            with entry["source"].open("rb") as stream:
                                archive.addfile(info, stream)
            compressed = Path(tmp) / name
            subprocess.run(["zstd", "-q", "-T1", "-19", str(tar_path), "-o", str(compressed)], check=True)
            os.replace(compressed, destination)
        (self.output / f"{package}.provenance.json").write_bytes(json_bytes(provenance))
        return {"name": package, "version": SPECS[package]["version"], "filename": name, "sha256": digest_file(destination), "bytes": destination.stat().st_size, "installed_size": size, "payload_files": len(self.entries[package]), "source_packages": provenance["source_packages"]}

    def run(self) -> dict:
        self.select()
        self.output.mkdir(parents=True, exist_ok=True)
        result = {"schema": 1, "vendor_release": RELEASE_URL, "kernel_release": KERNEL, "source_date_epoch": self.epoch, "recipe_sha256": digest_file(Path(__file__)), "warnings": self.warnings, "excluded_files": self.exclusions, "packages": []}
        for package in SPECS:
            print(f"Packaging {package}: {len(self.entries[package])} files", flush=True)
            result["packages"].append(self.archive(package))
        (self.output / "bsp-manifest.json").write_bytes(json_bytes(result))
        (self.output / "SHA256SUMS.bsp").write_text("".join(f"{package['sha256']}  {package['filename']}\n" for package in result["packages"]), encoding="utf-8")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-root", type=Path, required=True, help="Extracted official T5 rootfs (read only)")
    parser.add_argument("--output", type=Path, required=True, help="Output directory; regular files only, never a block device")
    parser.add_argument("--source-date-epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "1789344000")))
    args = parser.parse_args()
    if not shutil.which("zstd"):
        parser.error("zstd is required on the build host")
    if not args.vendor_root.is_dir():
        parser.error("--vendor-root must be a directory")
    if args.output.exists() and not args.output.is_dir():
        parser.error("--output must be a directory")
    vendor = args.vendor_root.resolve()
    output = args.output.resolve()
    if output == vendor or vendor in output.parents:
        parser.error("--output must be outside --vendor-root to keep the input read only")
    try:
        result = Builder(vendor, output, args.source_date_epoch).run()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"BSP packaging failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"packages": len(result["packages"]), "manifest": str(output / "bsp-manifest.json"), "warnings": result["warnings"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
