#!/usr/bin/env python3
"""Repackage the fixed T5 PowerVR userspace without replacing Arch libraries.

Run on Linux; host tools: readelf, patchelf, tar, zstd. The input must be an
extracted official T5 rootfs including /var/lib/dpkg. No input is modified.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

PACKAGE = "xserver-xorg-img-bxm-1.21.1-2.deb"
VERSION = "24.2.6603887_t5-3"
COMPAT_VERSION = "1.1.1n_t5-3"
PRIVATE = Path("usr/lib/radxa-a7z-gpu")
REPO = Path(__file__).resolve().parents[1]
CORE_DEPS = ["glibc", "gcc-libs", "libdrm", "libx11", "libxcb", "libxshmfence",
             "expat", "zlib", "systemd-libs", "vulkan-icd-loader",
             "radxa-a7z-gpu-kmod=0.1.0_3-1"]
XORG_DEPS = [f"radxa-a7z-gpu-userspace={VERSION}",
             f"radxa-a7z-gpu-compat={COMPAT_VERSION}", "libpciaccess", "pixman",
             "libxfont2", "libxau", "libxdmcp", "libepoxy", "libxcvt",
             "xkeyboard-config", "xorg-xkbcomp"]


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, env={**os.environ, "LC_ALL": "C"})


def rooted(root: Path, relative: str | Path) -> Path:
    """Resolve absolute symlinks inside the foreign root, never against the host."""
    parts = list(PurePosixPath(str(relative).lstrip("/")).parts)
    resolved: list[str] = []
    links = 0
    while parts:
        item = parts.pop(0)
        if item in ("", "."):
            continue
        if item == "..":
            if not resolved:
                raise ValueError(f"path escapes vendor root: {relative}")
            resolved.pop()
            continue
        p = root.joinpath(*resolved, item)
        if p.is_symlink():
            links += 1
            if links > 40:
                raise ValueError(f"symlink loop: {relative}")
            target = os.readlink(p)
            if target.startswith("/"):
                resolved = []
            parts = list(PurePosixPath(target).parts)[int(target.startswith("/")):] + parts
        else:
            resolved.append(item)
    return root.joinpath(*resolved)


def sha256(path: Path) -> str:
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def is_elf(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    with path.open("rb") as src:
        return src.read(4) == b"\x7fELF"


def elf_info(path: Path) -> dict:
    dynamic = run("readelf", "-Wd", str(path))
    header = run("readelf", "-Wh", str(path))
    symbols = run("readelf", "-Ws", str(path))
    version_data = run("readelf", "-WV", str(path))
    versions: dict[str, list[str]] = {}
    current = None
    in_needs = False
    for line in version_data.splitlines():
        if "Version needs section" in line:
            in_needs = True
        elif "Version " in line and "section" in line:
            in_needs = False
        if not in_needs:
            continue
        match = re.search(r"File: (\S+)", line)
        if match:
            current = match[1]
            versions[current] = []
        match = re.search(r"Name: (\S+)", line)
        if match and current:
            versions[current].append(match[1])
    exported = set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[0].rstrip(":").isdigit() and fields[6] != "UND":
            exported.add(fields[7].split("@")[0])
    return {
        "aarch64": "AArch64" in header,
        "needed": re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic),
        "soname": next(iter(re.findall(r"\(SONAME\).*?\[(.*?)\]", dynamic)), None),
        "rpath": re.findall(r"\((?:RPATH|RUNPATH)\).*?\[(.*?)\]", dynamic),
        "version_needs": versions,
        "glvnd_egl_entrypoint": "__egl_Main" in exported,
        "vulkan_icd_entrypoint": "vk_icdGetInstanceProcAddr" in exported,
        "exports": exported,
        "version_definitions": set(re.findall(r"Name: (\S+)", version_data.split("Version needs section")[0])),
    }


def dpkg_version(root: Path, package: str) -> str:
    status = rooted(root, "var/lib/dpkg/status")
    for paragraph in status.read_text().split("\n\n"):
        fields = dict(re.findall(r"^(\S+): (.*)$", paragraph, re.M))
        if fields.get("Package") == package:
            if fields.get("Status") != "install ok installed":
                raise ValueError(f"vendor package is not installed: {package}")
            return fields["Version"]
    raise ValueError(f"missing dpkg record for {package}")


def package_files(root: Path, package: str) -> list[str]:
    candidates = [root / "var/lib/dpkg/info" / (package + suffix)
                  for suffix in (".list", ":arm64.list")]
    lists = [p for p in candidates if p.is_file()]
    if len(lists) != 1:
        raise ValueError(f"expected one installed file list for {package}: {lists}")
    return [p.lstrip("/") for p in lists[0].read_text().splitlines() if p != "/."]


def destination(relative: str) -> tuple[str, Path] | None:
    p = PurePosixPath(relative)
    if relative == "usr/bin/Xorg":
        return "xorg", PRIVATE / "xorg/Xorg"
    if relative.startswith("usr/lib/xorg/modules/"):
        return "xorg", PRIVATE / "xorg/modules" / p.relative_to("usr/lib/xorg/modules")
    if relative.startswith("usr/local/lib/dri/") and p.name.endswith(".so"):
        return "userspace", PRIVATE / "dri" / p.name
    if str(p.parent) in ("usr/lib", "usr/local/lib") and ".so" in p.name:
        # Use Arch's Vulkan loader and OpenCL loader, retaining the actual ICDs.
        if p.name.startswith(("libvulkan.so", "libOpenCL.so", "libxcvt.so")):
            return None
        return "userspace", PRIVATE / "lib" / p.name
    return None


def install_file(root: Path, source: str, stage: Path, dest: Path, provenance: list) -> None:
    source_parts = PurePosixPath(source)
    original = rooted(root, str(source_parts.parent)) / source_parts.name
    actual = rooted(root, source)
    if not actual.is_file():
        raise ValueError(f"missing vendor file: {source}")
    target = stage / dest
    target.parent.mkdir(parents=True, exist_ok=True)
    if original.is_symlink():
        target.symlink_to(actual.name)
    else:
        shutil.copy2(actual, target)
        target.chmod(0o755 if actual.stat().st_mode & 0o111 else 0o644)
    provenance.append({"source": source, "destination": str(dest), "sha256": sha256(actual),
                       "source_link": os.readlink(original) if original.is_symlink() else None})


def docs(root: Path, package: str, stage: Path, destination_name: str) -> None:
    src = rooted(root, f"usr/share/doc/{package}")
    out = stage / "usr/share/licenses" / destination_name / package
    out.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for p in src.rglob("*"):
            if p.is_file() and not p.is_symlink():
                target = out / p.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    if not any(out.iterdir()):
        (out / "UPSTREAM-NOTICE.txt").write_text(
            f"The installed official T5 {package} package contains no copyright file.\n"
            "The extracted binaries retain their embedded notices. No new redistribution\n"
            "license is granted by this repackaging; obtain the original vendor terms\n"
            "before distributing a public image containing these proprietary components.\n")


def write(stage: Path, relative: str | Path, content: str, executable: bool = False) -> None:
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755 if executable else 0o644)


def normalize_elf(stage: Path) -> None:
    libdir = stage / PRIVATE / "lib"
    compat = stage / PRIVATE / "compat"
    for p in stage.rglob("*"):
        if is_elf(p):
            if not elf_info(p)["aarch64"]:
                raise ValueError(f"non-AArch64 ELF in GPU payload: {p}")
            # Remove vendor DT_RPATH=/usr/local/lib. Per-object RUNPATH preserves
            # lookup for dlopen/ICD while keeping the entire installation private.
            paths = []
            for d in (libdir, compat):
                rel = os.path.relpath(d, p.parent)
                paths.append("$ORIGIN" if rel == "." else "$ORIGIN/" + rel)
            subprocess.run(["patchelf", "--set-rpath", ":".join(paths), str(p)], check=True)


def dependency_report(stages: dict[str, Path], target: Path | None) -> dict:
    private = {}
    objects = {}
    for name, stage in stages.items():
        for p in stage.rglob("*"):
            if p.is_file() and ".so" in p.name:
                private.setdefault(p.name, (p, name))
            if is_elf(p):
                info = elf_info(p)
                objects[f"{name}:{p.relative_to(stage)}"] = (p, info)
    missing, mismatches, entries = [], [], []
    cache = {}
    def describe(path):
        for name, stage in stages.items():
            if path.is_relative_to(stage):
                return f"{name}:/{path.relative_to(stage)}"
        if target and path.is_relative_to(target):
            return f"target:/{path.relative_to(target)}"
        return str(path)
    def resolve(soname):
        if soname in private:
            return private[soname][0], "private"
        if target:
            for directory in ("usr/lib", "lib", "usr/lib/aarch64-linux-gnu", "lib/aarch64-linux-gnu"):
                p = rooted(target, f"{directory}/{soname}")
                if p.is_file():
                    return p, "target"
        return None, "missing" if target else "not-checked"
    pending = [(key, path, info) for key, (path, info) in objects.items()]
    seen = set()
    while pending:
        key, path, info = pending.pop(0)
        real = str(path.resolve())
        if real in seen:
            continue
        seen.add(real)
        resolved = []
        for needed in info["needed"]:
            provider, origin = resolve(needed)
            entry = {"soname": needed, "provider": describe(provider) if provider else None, "origin": origin}
            resolved.append(entry)
            if not provider:
                if target:
                    missing.append({"object": key, "soname": needed})
                continue
            provider_key = str(provider.resolve())
            if provider_key not in cache:
                cache[provider_key] = elf_info(provider)
            provider_info = cache[provider_key]
            if not provider_info["aarch64"]:
                mismatches.append({"object": key, "provider": describe(provider), "reason": "not AArch64"})
            for version in info["version_needs"].get(needed, []):
                if version not in provider_info["version_definitions"]:
                    mismatches.append({"object": key, "soname": needed, "missing_version": version})
            pending.append((describe(provider), provider, provider_info))
        entries.append({"object": key, "needed": resolved, "runpath": info["rpath"],
                        "version_needs": info["version_needs"]})
    return {"target_root": str(target) if target else None,
            "status": "unchecked" if not target else ("blocked" if missing or mismatches else "static-dependencies-pass"),
            "hardware_validation": "not-run", "missing": missing, "version_mismatches": mismatches,
            "objects": entries,
            "limits": "DT_NEEDED and symbol-version checks do not prove dlopen symbols, Xorg module ABI or GPU operation."}


def archive(stage: Path, output: Path, name: str, version: str, deps: list[str], epoch: int) -> Path:
    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file() and not p.is_symlink())
    metadata = [f"pkgname = {name}", f"pkgbase = {name}", f"pkgver = {version}",
                "pkgdesc = Radxa Cubie A7Z T5 isolated PowerVR userspace (experimental)",
                "url = https://github.com/radxa-pkg/allwinner-prebuilt", f"builddate = {epoch}",
                "packager = A7Z Arch Linux ARM port", f"size = {size}", "arch = aarch64",
                "license = custom:vendor-see-UPSTREAM-NOTICE"]
    metadata.extend("depend = " + dep for dep in deps)
    if name == "radxa-a7z-gpu-userspace":
        metadata.append("optdepend = python: a7z-gpu-probe diagnostic")
    write(stage, ".PKGINFO", "\n".join(metadata) + "\n")
    for p in stage.rglob("*"):
        os.utime(p, (epoch, epoch), follow_symlinks=False)
    os.utime(stage, (epoch, epoch))
    if shutil.which("bsdtar"):
        data = subprocess.check_output(["bsdtar", "--format=mtree", "--options=!all,use-set,type,uid,gid,mode,time,size,sha256,link", "-cf", "-", "."], cwd=stage)
        # bsdtar uses host IDs; build as root or normalize the mtree as tar does.
        data = re.sub(rb"\b(?:uid|gid)=\d+", lambda m: m[0].split(b"=")[0] + b"=0", data)
        (stage / ".MTREE").write_bytes(gzip.compress(data, mtime=epoch))
    result = output / f"{name}-{version}-aarch64.pkg.tar.zst"
    subprocess.run(["tar", "--sort=name", "--format=posix", "--pax-option=delete=atime,delete=ctime",
                    f"--mtime=@{epoch}", "--owner=0", "--group=0", "--numeric-owner", "--zstd",
                    "-cf", str(result), "-C", str(stage),
                    *sorted(p.name for p in stage.iterdir())], check=True)
    return result


def build(args) -> dict:
    root = args.vendor_root.resolve()
    target = args.target_root.resolve() if args.target_root else None
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    gpu_version = dpkg_version(root, PACKAGE)
    ssl_version = dpkg_version(root, "libssl1.1")
    if gpu_version != "1.0.1" or ssl_version != "1.1.1n-0+deb11u4":
        raise ValueError(f"not the fixed T5 packages: GPU={gpu_version}, libssl1.1={ssl_version}")
    provenance = []
    with tempfile.TemporaryDirectory(prefix="a7z-gpu-") as tmp:
        stages = {name: Path(tmp) / name for name in ("userspace", "compat", "xorg")}
        for stage in stages.values():
            stage.mkdir()
        for relative in package_files(root, PACKAGE):
            selected = destination(relative)
            if selected and rooted(root, relative).is_dir():
                continue
            if selected:
                name, dest = selected
                install_file(root, relative, stages[name], dest, provenance)
        required = ["libEGL.so.1", "libGLESv2.so.2", "libgbm.so.1", "libsrv_um.so", "libVK_IMG.so.1"]
        for name in required:
            if not (stages["userspace"] / PRIVATE / "lib" / name).is_file():
                raise ValueError(f"GPU package lacks {name}")
        egl = elf_info(stages["userspace"] / PRIVATE / "lib/libEGL.so.1")
        vk = elf_info(stages["userspace"] / PRIVATE / "lib/libVK_IMG.so.1")
        if not vk["vulkan_icd_entrypoint"]:
            raise ValueError("vendor Vulkan library lacks the ICD entry point")
        for relative in package_files(root, "libssl1.1"):
            if PurePosixPath(relative).name in ("libcrypto.so.1.1", "libssl.so.1.1"):
                install_file(root, relative, stages["compat"], PRIVATE / "compat" / PurePosixPath(relative).name, provenance)
        if not (stages["compat"] / PRIVATE / "compat/libcrypto.so.1.1").is_file():
            raise ValueError("T5 OpenSSL 1.1 compatibility library is absent")
        for name in ("userspace", "xorg"):
            docs(root, PACKAGE, stages[name], "radxa-a7z-gpu-" + name)
        docs(root, "libssl1.1", stages["compat"], "radxa-a7z-gpu-compat")
        # Queried from this fixed T5 ICD using vk_icdGetInstanceProcAddr(NULL,
        # "vkEnumerateInstanceVersion") under QEMU: VK_SUCCESS, 4206869.
        icd = {"file_format_version": "1.0.0", "ICD": {"library_path": "/usr/lib/radxa-a7z-gpu/lib/libVK_IMG.so.1", "api_version": "1.3.277"}}
        write(stages["userspace"], "usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json", json.dumps(icd, indent=2) + "\n")
        write(stages["userspace"], "usr/bin/a7z-gpu-run", (REPO / "gpu/a7z-gpu-run").read_text(), True)
        write(stages["userspace"], "usr/bin/a7z-gpu-probe", (REPO / "gpu/a7z-gpu-probe.py").read_text(), True)
        write(stages["userspace"], "usr/bin/a7z-gpu-link-check", (REPO / "gpu/check_runtime.py").read_text(), True)
        write(stages["userspace"], "usr/bin/a7z-gpu-desktop", (REPO / "gpu/a7z-gpu-desktop.py").read_text(), True)
        write(stages["userspace"], PRIVATE / "arch-Xorg", (REPO / "gpu/a7z-arch-xorg").read_text(), True)
        write(stages["userspace"], "usr/share/doc/radxa-a7z-gpu-userspace/DESKTOP.zh-CN.md", (REPO / "gpu/DESKTOP.zh-CN.md").read_text())
        write(stages["xorg"], "usr/bin/a7z-xorg", (REPO / "gpu/a7z-xorg").read_text(), True)
        config = rooted(root, "etc/X11/xorg.conf.d/20-modesetting.conf")
        if config.is_file():
            write(stages["xorg"], "usr/share/radxa-a7z-gpu/xorg.conf.d/20-modesetting.conf", config.read_text())
        for name, stage in stages.items():
            write(stage, "usr/share/doc/radxa-a7z-gpu-" + name + "/README.zh-CN.md", (REPO / "gpu/README.zh-CN.md").read_text())
            normalize_elf(stage)
        for record in provenance:
            for stage in stages.values():
                installed = stage / record["destination"]
                if installed.is_file():
                    record["installed_sha256"] = sha256(installed)
                    break
        components = getattr(args, "components", "all")
        selected_stages = stages if components == "all" else {"userspace": stages["userspace"]}
        report = dependency_report(selected_stages, target)
        report.update({"baseline": "rsdk-t5", "vendor_package": PACKAGE, "vendor_version": gpu_version,
                       "driver_version": "24.2.6603887", "bvnc": "36.56.104.183",
                       "openssl_compat_version": ssl_version,
                       "egl_glvnd_supported": egl["glvnd_egl_entrypoint"],
                       "vulkan_icd_supported": vk["vulkan_icd_entrypoint"],
                       "audited_components": list(selected_stages),
                       "provenance": provenance,
                       "excluded": ["kernel modules and firmware (BSP package)", "vendor libvulkan loader",
                                    "vendor OpenCL loader", "global ld.so.conf/environment", "global Xorg/LightDM replacement"]})
        artifacts = []
        if not args.inspect_only:
            for name, stage in selected_stages.items():
                pkgname = "radxa-a7z-gpu-" + name
                version = COMPAT_VERSION if name == "compat" else VERSION
                deps = CORE_DEPS if name == "userspace" else XORG_DEPS if name == "xorg" else ["glibc"]
                public_report = {k: v for k, v in report.items() if k != "objects"}
                write(stage, f"usr/share/doc/{pkgname}/build-report.json", json.dumps(public_report, indent=2) + "\n")
                path = archive(stage, output, pkgname, version, deps, args.epoch)
                artifacts.append({"path": str(path), "sha256": sha256(path)})
        report["artifacts"] = artifacts
        (output / "gpu-dependency-report.json").write_text(json.dumps(report, indent=2) + "\n")
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, help="Arch rootfs for recursive DT_NEEDED and symbol-version audit")
    parser.add_argument("--inspect-only", action="store_true", help="write dependency/provenance report without archives")
    parser.add_argument("--strict", action="store_true", help="require a target-root and no missing static dependencies")
    parser.add_argument("--components", choices=("all", "userspace"), default="all",
                        help="only package/audit selected components; userspace avoids optional vendor Xorg dependencies")
    parser.add_argument("--epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "1789344000")))
    args = parser.parse_args()
    for tool in ("readelf", "patchelf", "tar", "zstd"):
        if not shutil.which(tool):
            parser.error(f"Linux build tool required: {tool}")
    if args.strict and not args.target_root:
        parser.error("--strict requires --target-root")
    try:
        report = build(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"GPU packaging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("status", "egl_glvnd_supported", "vulkan_icd_supported", "artifacts", "missing", "version_mismatches")}, indent=2))
    return 1 if args.strict and report["status"] != "static-dependencies-pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
