#!/usr/bin/env python3
"""Prepare a locked HDMI kernel input or rebuild it from pinned T5 sources.

No board access, package installation, or changes to the vendor rootfs. The
result is a package_bsp.py input directory, not a bootable disk image.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "kernel/hdmi/build-input.lock.json"
RELEASE = "6.6.98-4-aw2511"
FIX = "hdmi-hpd-atomic-state"
OUTPUTS = ("Image", "config", "System.map")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def load_lock() -> dict:
    lock = json.loads(LOCK_PATH.read_text())
    if lock["schema"] != 1 or lock["kernel_release"] != RELEASE or lock["fix"] != FIX:
        raise ValueError("Unexpected HDMI source/input lock")
    patch = REPO / lock["patch"]["path"]
    if digest(patch) != lock["patch"]["sha256"]:
        raise ValueError("HDMI patch differs from the source lock")
    return lock


def config_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_"):
            key, value = line.split("=", 1)
            values[key] = value
        elif match := re.fullmatch(r"# (CONFIG_\w+) is not set", line):
            values[match[1]] = "n"
    return values


def records(directory: Path) -> dict:
    return {name: {"bytes": (directory / name).stat().st_size,
                   "sha256": digest(directory / name)} for name in OUTPUTS}


def public_report(lock: dict, method: str, outputs: dict, build: dict) -> dict:
    return {"schema": 1, "fix": FIX, "kernel_release": RELEASE, "method": method,
            "input_lock_sha256": digest(LOCK_PATH), "patch": lock["patch"],
            "source_archives": lock["source_archives"],
            "original_config_sha256": lock["original_config_sha256"],
            "outputs": outputs, "build": build,
            "modules_and_dtbs": "Original T5 payloads; same kernel release and functional configuration",
            "scope": "HPD handling only. No forced HPD or fixed mode. Existing atomic and PM callbacks own transmitter state.",
            "limitations": ["CLI startup and same-display reconnect were observed before this release build.",
                            "This release build does not run hardware or desktop tests.",
                            "Different-display mode selection, HDCP reauthentication and suspend/resume are not claimed validated."]}


def load_kernel_input(directory: Path, vendor_root: Path) -> tuple[dict[str, bytes], dict]:
    """Validate the immutable input contract and return public-only provenance."""
    lock = load_lock()
    directory = directory.resolve()
    for name in (*OUTPUTS, "provenance.json"):
        path = directory / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError("Missing or non-regular HDMI input: " + name)
    report = json.loads((directory / "provenance.json").read_text())
    if (report.get("schema") != 1 or report.get("fix") != FIX or
            report.get("kernel_release") != RELEASE or
            report.get("input_lock_sha256") != digest(LOCK_PATH) or
            report.get("patch") != lock["patch"] or
            report.get("source_archives") != lock["source_archives"] or
            report.get("original_config_sha256") != lock["original_config_sha256"]):
        raise ValueError("HDMI input provenance does not match the locked source recipe")
    actual = records(directory)
    if actual != report.get("outputs"):
        raise ValueError("HDMI input bytes do not match their provenance")
    method = report.get("method")
    build = report.get("build")
    if method == "locked-build-input":
        if actual != lock["locked_build"]["outputs"] or build != lock["locked_build"]["build"]:
            raise ValueError("Locked HDMI candidate output mismatch")
    elif method == "source-build":
        # Keep arbitrary local command lines/paths out of the installed report.
        expected_keys = {"compiler_version", "binutils_version", "source_date_epoch",
                         "build_user", "build_host", "build_version", "config_diff"}
        if (not isinstance(build, dict) or set(build) != expected_keys or
                build["compiler_version"] != "14.2.0" or build["binutils_version"] != "2.44" or
                build["build_user"] != "builder" or build["build_host"] != "a7z-hdmi" or
                build["build_version"] != "1" or
                not isinstance(build["source_date_epoch"], int) or build["source_date_epoch"] < 0):
            raise ValueError("Unexpected HDMI source-build metadata")
    else:
        raise ValueError("Unknown HDMI input method; original vendor Image is never a fallback")
    vendor_config = vendor_root / f"boot/config-{RELEASE}"
    if digest(vendor_config) != lock["original_config_sha256"]:
        raise ValueError("Vendor kernel configuration differs from the locked T5 configuration")
    if digest(vendor_root / f"boot/vmlinuz-{RELEASE}") != lock["original_image_sha256"]:
        raise ValueError("Vendor kernel Image differs from the locked T5 input")
    old, new = config_values(vendor_config), config_values(directory / "config")
    changes = {key: {"old": old.get(key), "new": new.get(key)}
               for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)}
    if set(changes) - {"CONFIG_CC_VERSION_TEXT"} or changes != build["config_diff"]:
        raise ValueError("HDMI kernel changed functional configuration or provenance disagrees")
    if new.get("CONFIG_MODVERSIONS") != "n" or new.get("CONFIG_RELR") != "y":
        raise ValueError("Unexpected module ABI or RELR configuration")
    payloads = {name: (directory / name).read_bytes() for name in OUTPUTS}
    image = payloads["Image"]
    identity = ("a7z-hdmi-fix@cli-candidate1" if method == "locked-build-input" else "builder@a7z-hdmi")
    if len(image) < 64 or image[56:60] != b"ARMd" or RELEASE.encode() not in image or identity.encode() not in image:
        raise ValueError("HDMI kernel is not the expected raw ARM64 Image")
    if hashlib.sha256(image).hexdigest() == lock["original_image_sha256"]:
        raise ValueError("Refusing unpatched original vendor kernel")
    return payloads, public_report(lock, method, actual, build)


def prepare_input(source: Path, output: Path) -> None:
    lock = load_lock()
    actual = records(source)
    if actual != lock["locked_build"]["outputs"]:
        raise ValueError("Candidate Image/config/System.map do not match the locked build")
    output.mkdir(parents=True, exist_ok=False)
    for name in OUTPUTS:
        shutil.copyfile(source / name, output / name)
    report = public_report(lock, "locked-build-input", actual, lock["locked_build"]["build"])
    (output / "provenance.json").write_bytes(json_bytes(report))


def extract(archive: Path, destination: Path, record: dict) -> None:
    if digest(archive) != record["sha256"] or archive.stat().st_size != record["bytes"]:
        raise ValueError("Source archive mismatch: " + record["name"])
    top = record["repo"].split("/")[-1] + "-" + record["commit"]
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if any(m.name != top and not m.name.startswith(top + "/") for m in members):
            raise ValueError("Unexpected source archive root")
        # BSP ramfs templates contain absolute /proc and /dev symlinks. They
        # are unused because the locked kernel has CONFIG_INITRAMFS_SOURCE="".
        members = [m for m in members if not (record["name"] == "bsp" and m.name.startswith(top + "/ramfs/"))]
        source.extractall(destination, members=members, filter="data")
    target = destination / record["name"]
    if record["name"] == "src" and (target / "bsp").is_symlink():
        if os.readlink(target / "bsp") != "../bsp":
            raise ValueError("Unexpected wrapper BSP symlink")
        (target / "bsp").unlink()
    if target.is_dir():
        if any(target.iterdir()):
            raise ValueError("Expected an empty source gitlink directory")
        target.rmdir()
    (destination / top).rename(target)


def source_build(args) -> None:
    lock = load_lock()
    if platform.system() != "Linux":
        raise ValueError("Source builds require Linux; WSL is supported")
    if args.jobs < 1 or args.jobs > 256 or args.source_date_epoch < 0:
        raise ValueError("Invalid jobs or source-date-epoch")
    vendor = args.vendor_root.resolve()
    headers = vendor / f"usr/src/linux-headers-{RELEASE}"
    if digest(headers / ".config") != lock["original_config_sha256"]:
        raise ValueError("Vendor configuration mismatch")
    if digest(headers / "bsp/include/sunxi-autogen.h") != lock["sunxi_autogen_sha256"]:
        raise ValueError("Vendor generated BSP header mismatch")
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    bindir = args.binutils_prefix.resolve() / "bin"
    target_bin = args.binutils_prefix.resolve() / "aarch64-linux-gnu/bin"
    cross = str(bindir / "aarch64-linux-gnu-")
    cc_version = subprocess.check_output([str(compiler), "-dumpfullversion"], text=True).strip()
    ld_version = subprocess.check_output([cross + "ld", "--version"], text=True).splitlines()[0]
    as_version = subprocess.check_output([cross + "as", "--version"], text=True).splitlines()[0]
    if cc_version != "14.2.0" or not ld_version.endswith(" 2.44") or not as_version.endswith(" 2.44"):
        raise ValueError("Use GCC 14.2.0 and GNU binutils 2.44 to preserve the T5 configuration")
    work = args.work_dir.resolve()
    if work.exists() or args.output.exists():
        raise ValueError("Source build work/output directories must be new")
    if work == vendor or work.is_relative_to(vendor) or args.output.resolve().is_relative_to(vendor):
        raise ValueError("Build outputs must be outside the read-only vendor tree")
    work.mkdir(parents=True)
    for record in sorted(lock["source_archives"], key=lambda r: r["name"] != "wrapper"):
        archive = args.archives / (record["name"] + "-" + record["commit"] + ".tar.gz")
        extract(archive, work if record["name"] == "wrapper" else work / "wrapper", record)
    source, bsp = work / "wrapper/src", work / "wrapper/bsp"
    (source / "bsp").symlink_to("../bsp", target_is_directory=True)
    (source / "arch/arm64/configs/bsp.config").symlink_to("../../../../device-a733/configs/default/linux-6.6/bsp_defconfig")
    for model in ("a7a", "a7s", "a7z"):
        (source / f"arch/arm64/boot/dts/allwinner/sun60i-a733-cubie-{model}.dts").symlink_to(
            f"../../../../../../device-a733/configs/cubie_{model}/linux-6.6/board.dts")
    for path in (bsp / "configs/linux-6.6").glob("*.dtsi"):
        shutil.copyfile(path, source / "arch/arm64/boot/dts/allwinner" / path.name)
    shutil.copytree(bsp / "include/dt-bindings", source / "include/dt-bindings", dirs_exist_ok=True)
    shutil.copyfile(headers / "bsp/include/sunxi-autogen.h", bsp / "include/sunxi-autogen.h")
    shutil.copyfile(headers / ".config", source / ".config")
    driver = bsp / "drivers/drm/sunxi_drm_hdmi.c"
    if digest(driver) != lock["patch"]["source_sha256"]:
        raise ValueError("Unexpected original HDMI driver")
    subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(REPO / lock["patch"]["path"])], cwd=bsp, check=True)
    if digest(driver) != lock["patch"]["patched_source_sha256"]:
        raise ValueError("Unexpected patched HDMI driver")
    stamp = datetime.datetime.fromtimestamp(args.source_date_epoch, datetime.timezone.utc)
    env = dict(os.environ, LC_ALL="C", LANG="C", SOURCE_DATE_EPOCH=str(args.source_date_epoch),
               KBUILD_BUILD_USER="builder", KBUILD_BUILD_HOST="a7z-hdmi", KBUILD_BUILD_VERSION="1",
               KBUILD_BUILD_TIMESTAMP=stamp.strftime("%a %b %d %H:%M:%S UTC %Y"))
    make = ["make", f"-j{args.jobs}", "ARCH=arm64", "CROSS_COMPILE=" + cross,
            "CC=" + str(compiler) + " -B" + str(target_bin) + "/", "HOSTCC=gcc", "HOSTCXX=g++",
            "BSP_TOP=bsp/", "LICHEE_KERN_DIR=./", "KBUILD_DEFCONFIG=bsp.config",
            "CFLAGS_sunxi-gmac.o=-I" + str(bsp / "drivers/gmac"),
            *["CFLAGS_" + name + ".o=-I" + str(bsp / "drivers/usb/host")
              for name in ("ehci-sunxi", "ohci-sunxi", "sunxi-hci")],
            "KCFLAGS=-ffile-prefix-map=" + str(work) + "=/build/a7z-hdmi -fmacro-prefix-map=" + str(work) + "=/build/a7z-hdmi",
            "LOCALVERSION=-4-aw2511", "KERNELRELEASE=" + RELEASE]
    def run(target: str) -> None:
        print("Building HDMI kernel: " + target, flush=True)
        with (work / (target + ".log")).open("xb") as log:
            process = subprocess.Popen(make + [target], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    print("Building HDMI kernel: " + target, flush=True)
            if process.returncode:
                raise RuntimeError("Kernel " + target + " failed; see the build work directory log")
    run("olddefconfig")
    old, new = config_values(headers / ".config"), config_values(source / ".config")
    diff = {key: {"old": old.get(key), "new": new.get(key)}
            for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)}
    if set(diff) - {"CONFIG_CC_VERSION_TEXT"}:
        raise ValueError("Compiler changed functional T5 configuration")
    run("Image")
    if (source / "include/generated/utsrelease.h").read_text().strip() != '#define UTS_RELEASE "' + RELEASE + '"':
        raise ValueError("Built kernel release mismatch")
    args.output.mkdir(parents=True)
    for name, relative in (("Image", "arch/arm64/boot/Image"), ("config", ".config"), ("System.map", "System.map")):
        shutil.copyfile(source / relative, args.output / name)
    build = {"compiler_version": cc_version, "binutils_version": "2.44", "source_date_epoch": args.source_date_epoch,
             "build_user": "builder", "build_host": "a7z-hdmi", "build_version": "1", "config_diff": diff}
    (args.output / "provenance.json").write_bytes(json_bytes(public_report(lock, "source-build", records(args.output), build)))
    load_kernel_input(args.output, vendor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-input", help="Copy only locked artifacts and replace private build records with public provenance")
    prepare.add_argument("--candidate", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build", help="Build from local pinned source archives; does not install host tools")
    build.add_argument("--vendor-root", type=Path, required=True)
    build.add_argument("--archives", type=Path, required=True)
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cc", default="aarch64-linux-gnu-gcc-14")
    build.add_argument("--binutils-prefix", type=Path, required=True)
    build.add_argument("--jobs", type=int, default=4)
    build.add_argument("--source-date-epoch", type=int, default=1789484513)
    args = parser.parse_args()
    if args.command == "prepare-input":
        prepare_input(args.candidate, args.output)
    else:
        source_build(args)
    print(json.dumps({"kernel_release": RELEASE, "outputs": records(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
