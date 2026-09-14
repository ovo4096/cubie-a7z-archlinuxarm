#!/usr/bin/env python3
"""Export audit records for already-built images without rebuilding or flashing.

Only named audit files and package copies are written. Existing .img/.zst files
are read and verified; they are never replaced. Run as Linux root for pacman -Q
in the prepared rootfs. No rootfs mutation or physical disk access is performed.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import build

AUDIT_NAMES = {"build-manifest.json", "SHA256SUMS", "sources.lock.json", "pacman-packages.txt",
               "pacman-cache-sha256.json", "build-recipes-sha256.json"}


def write_audit(output, name, content, replace):
    if name not in AUDIT_NAMES:
        raise ValueError("Unrecognized audit output name")
    target = output / name
    if target.is_symlink() or (target.exists() and not replace):
        raise ValueError(f"Audit file exists; pass --replace-audit if replacement is intended: {target}")
    if isinstance(content, (dict, list)):
        build.atomic_json(target, content)
    else:
        temporary = target.with_name(target.name + ".new")
        if isinstance(content, bytes):
            with temporary.open("wb") as handle:
                handle.write(content)
        else:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(content)
        temporary.replace(target)


def verify_compressed(compressed, raw_checksum):
    process = subprocess.Popen(["zstd", "-dc", str(compressed)], stdout=subprocess.PIPE)
    checksum = hashlib.sha256()
    for chunk in iter(lambda: process.stdout.read(8 * 1024 * 1024), b""):
        checksum.update(chunk)
    process.stdout.close()
    if process.wait() != 0 or checksum.hexdigest() != raw_checksum:
        raise ValueError(f"Compressed image does not match the raw image: {compressed}")


def export(args):
    output = build.safe_directory(args.output, "output directory")
    root = build.safe_directory(args.rootfs, "rootfs")
    if not output.is_dir() or not (root / "usr/bin/pacman").is_file():
        raise ValueError("Existing output directory and prepared Arch rootfs are required")
    for name in AUDIT_NAMES:
        target = output / name
        if target.is_symlink() or (target.exists() and not args.replace_audit):
            raise ValueError(f"Refusing existing audit file: {target}; --replace-audit affects audit files only")
    lock_path = Path(args.lock).resolve(strict=True)
    lock = json.loads(lock_path.read_text())
    build.script("sources.py", "verify", "--cache", args.source_cache, "--lock", lock_path)
    images = []
    for image in sorted(output.glob("*.img")):
        if image.is_symlink() or not image.is_file():
            raise ValueError("Image inputs must be regular files")
        meta_path = Path(str(image) + ".json")
        metadata = json.loads(meta_path.read_text())
        checksum = build.digest(image)
        if checksum != metadata["sha256"] or image.stat().st_size != metadata["disk_bytes"]:
            raise ValueError(f"Image metadata/hash mismatch: {image}")
        sidecar = Path(str(image) + ".sha256").read_text().strip()
        if sidecar != f"{checksum}  {image.name}":
            raise ValueError(f"Image SHA256 sidecar mismatch: {image}")
        compressed = Path(str(image) + ".zst")
        if compressed.is_file():
            print(f"Verifying compressed contents: {compressed.name}", flush=True)
            verify_compressed(compressed, checksum)
        images.append({"filename": image.name, **metadata})
    if len(images) != 2 or {item["sector_size"] for item in images} != {512, 4096}:
        raise ValueError("Expected exactly one 512-byte SD image and one 4096-byte UFS image")
    if len({item["filesystem_uuids"]["rootfs"] for item in images}) != 2:
        raise ValueError("SD/UFS root filesystem UUIDs are not distinct")
    for item in images:
        if "private_seed_included" in item and item["private_seed_included"] != args.private_seed:
            raise ValueError("Private seed declaration conflicts with image metadata")
    snapshot = build.run("chroot", root, "/usr/bin/pacman", "-Q", capture=True) + "\n"
    for package_dir in args.package_dir:
        directory = Path(package_dir).resolve(strict=True)
        for source in sorted(directory.rglob("*")):
            if source.is_file() and not source.is_symlink() and source.name != "SHA256SUMS":
                if source.name.endswith((".pkg.tar.zst", ".json")) or source.name.startswith("SHA256SUMS."):
                    build.copy_verified(source, output / "packages" / source.name)
    for item in lock["artifacts"]:
        if item["role"] == "vendor-metadata":
            build.copy_verified(Path(args.source_cache) / item["name"], output / "upstream" / item["name"])
    cache = Path(args.package_cache).resolve(strict=True)
    cache_records = build.file_records(cache.rglob("*"), cache)
    recipes = build.file_records(build.recipe_files(), build.REPO)
    write_audit(output, "sources.lock.json", lock_path.read_bytes(), args.replace_audit)
    write_audit(output, "pacman-packages.txt", snapshot, args.replace_audit)
    write_audit(output, "pacman-cache-sha256.json", cache_records, args.replace_audit)
    write_audit(output, "build-recipes-sha256.json", recipes, args.replace_audit)
    installed = [line for line in snapshot.splitlines() if line.startswith(("radxa-a7z-", "linux-radxa-a7z "))]
    vendor_xorg = any(line.startswith("radxa-a7z-gpu-xorg ") for line in installed)
    configuration = build.runtime_configuration(root)
    build.copy_audit_documents(output, replace=args.replace_audit)
    records = build.file_records((path for path in output.rglob("*")
                                 if path.name not in ("build-manifest.json", "SHA256SUMS")), output)
    manifest = {"schema": 1, "audit_mode": "existing-images-no-rebuild", "board": "radxa-cubie-a7z",
                "vendor_release": lock["vendor_release"], "kernel_release": lock["kernel_release"],
                "variant": args.variant, "private_seed_included": args.private_seed,
                "source_inputs_verified": True, "source_lock_sha256": build.digest(lock_path),
                "source_date_epoch": lock["source_date_epoch"], "audit_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "images": images, "installed_board_packages": installed, "desktop_configuration": configuration["desktop"],
                "pacman_runtime_configuration": configuration["pacman"],
                "vendor_xorg_package_installed": vendor_xorg,
                "gpu_note": "The arch-glamor selection runs the Arch Xorg binary with private T5 EGL/GBM; the optional vendor Xorg binary is separate. Inspect recorded configuration and hardware validation. GLX/AIGLX remains software; Vulkan device enumeration does not establish Vulkan rendering support.",
                "pacman_cache_files": len(cache_records), "artifacts": records,
                "hardware_validation": "Recorded separately by the operator; not asserted by this audit exporter.",
                "rebuild_limit": "The locked source archives and final image bytes were verified. pacman packages came from a rolling repository. Version/cache-hash snapshots audit this result but do not promise a future bit-identical rebuild. Recipe hashes were captured at audit time; retained manual build logs are needed to establish the exact recipes used earlier."}
    write_audit(output, "build-manifest.json", manifest, args.replace_audit)
    all_files = build.file_records((path for path in output.rglob("*") if path.name != "SHA256SUMS"), output)
    write_audit(output, "SHA256SUMS", "".join(f"{record['sha256']}  {record['path']}\n" for record in all_files), args.replace_audit)
    print(json.dumps({"output": str(output), "image_count": len(images), "pacman_package_count": len(snapshot.splitlines()),
                      "pacman_cache_files": len(cache_records), "installed_board_packages": installed,
                      "private_seed_included": args.private_seed, "files_checksummed": len(all_files)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--package-dir", required=True, action="append")
    parser.add_argument("--package-cache", required=True)
    parser.add_argument("--source-cache", default=str(build.REPO / ".cache/upstream"))
    parser.add_argument("--lock", default=str(build.REPO / "config/sources.lock.json"))
    parser.add_argument("--variant", choices=("xfce", "cli"), default="xfce")
    parser.add_argument("--private-seed", action="store_true", help="declare that the images themselves contain private config seeds")
    parser.add_argument("--replace-audit", action="store_true", help="replace only named audit records, never images or packages")
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("Run as root on Linux for the read-only chroot pacman query")
        export(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Audit export refused/failed: {exc}\n")


if __name__ == "__main__":
    main()
