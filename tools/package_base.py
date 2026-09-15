#!/usr/bin/env python3
"""Build the Arch A7Z runtime package from reviewed repository-owned files."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

# Reuse the BSP packager's tested deterministic tar/.PKGINFO/.MTREE emitter.
import package_bsp as bsp

PACKAGE = "radxa-a7z-base"
VERSION = "0.1.0-4"
SPEC = {
    "version": VERSION,
    "description": "Arch Linux ARM A7Z boot preparation, first boot and SD/UFS runtime tools",
    "depends": ["python", "bash", "coreutils", "kmod", "mkinitcpio", "util-linux", "e2fsprogs", "dosfstools", "gptfdisk", "cloud-guest-utils", "systemd", "linux-radxa-a7z=6.6.98_4-1", "radxa-a7z-bootloader", "radxa-a7z-wireless"],
    "licenses": ["MIT"],
}
BOOT_MAPPING = {
    "mkinitcpio-a7z.conf": "etc/mkinitcpio-a7z.conf",
    "linux-radxa-a7z.preset": "usr/share/a7z/linux-radxa-a7z.preset",
    "cmdline": "etc/kernel/cmdline",
    "50-a7z-boot-snapshot.hook": "usr/share/libalpm/hooks/50-a7z-boot-snapshot.hook",
    "99-a7z-boot-update.hook": "usr/share/libalpm/hooks/99-a7z-boot-update.hook",
    "extlinux.conf.example": "usr/share/a7z/extlinux.conf.example",
}
REQUIRED_RUNTIME = ("a7z-boot-update", "a7z-firstboot", "a7z-grow-root", "a7z-install-ufs", "a7z-firstboot.service", "a7z-grow-root.service")
BACKUPS = ("etc/kernel/cmdline", "etc/mkinitcpio-a7z.conf")


class BaseBuilder(bsp.Builder):
    def __init__(self, runtime, output, epoch):
        self.root, self.output, self.epoch = runtime.resolve(), output.resolve(), epoch
        self.entries = {PACKAGE: {}}
        self.sources = {PACKAGE: set()}
        self.module_info = []
        self.warnings = []

    def archive(self, package):
        previous = bsp.SPECS
        bsp.SPECS = {PACKAGE: SPEC}
        try:
            return super().archive(package)
        finally:
            bsp.SPECS = previous

    def select(self):
        for name in REQUIRED_RUNTIME:
            if not (self.root / name).is_file():
                raise ValueError(f"Required runtime source is missing: {name}")
        mapping = dict(BOOT_MAPPING)
        for source_name, destination in mapping.items():
            self.add(PACKAGE, "boot/" + source_name, "a7z-archlinux-port", destination)
        for source in sorted(self.root.glob("a7z-*")):
            if not source.is_file() or source.is_symlink():
                continue
            if source.name.endswith(".service"):
                destination, mode = "usr/lib/systemd/system/" + source.name, 0o644
            elif "." not in source.name:
                destination, mode = "usr/bin/" + source.name, 0o755
            else:
                continue
            self.add(PACKAGE, source.name, "a7z-archlinux-port", destination)
            self.entries[PACKAGE][destination]["mode"] = mode
        for entry in self.entries[PACKAGE].values():
            if entry["source_path"].startswith("boot/"):
                entry["mode"] = 0o644
        license_path = Path(__file__).resolve().parents[1] / "packages/base/LICENSE"
        self.generated(PACKAGE, f"usr/share/licenses/{PACKAGE}/LICENSE", data=license_path.read_bytes())

    def provenance(self, package):
        return {
            "schema": 1, "package": PACKAGE, "version": VERSION,
            "source_date_epoch": self.epoch, "kernel_release": bsp.KERNEL,
            "recipe_sha256": bsp.digest_file(Path(__file__)),
            "archive_emitter_sha256": bsp.digest_file(Path(bsp.__file__)),
            "method": "Repository runtime sources; no maintainer scripts and no storage writes while packaging",
            "files": {name: self.public_entry(entry) for name, entry in sorted(self.entries[PACKAGE].items())},
            "source_packages": [{"name": "a7z-archlinux-port", "version": VERSION}],
        }

    def pkginfo(self, package, size):
        return super().pkginfo(package, size) + "".join(f"backup = {name}\n" for name in BACKUPS).encode()

    def run(self):
        self.select()
        self.output.mkdir(parents=True, exist_ok=True)
        result = {"schema": 1, "source_date_epoch": self.epoch, "kernel_release": bsp.KERNEL, "packages": [self.archive(PACKAGE)]}
        (self.output / "base-manifest.json").write_bytes(bsp.json_bytes(result))
        (self.output / "SHA256SUMS.base").write_text("".join(f"{item['sha256']}  {item['filename']}\n" for item in result["packages"]), encoding="utf-8")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[1] / "runtime")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-date-epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "1789344000")))
    args = parser.parse_args()
    if not shutil.which("zstd"):
        parser.error("Build host requires zstd")
    if not args.runtime_root.is_dir():
        parser.error("--runtime-root must be a directory")
    if args.output.exists() and not args.output.is_dir():
        parser.error("--output must be a directory")
    try:
        result = BaseBuilder(args.runtime_root, args.output, args.source_date_epoch).run()
    except (ValueError, OSError) as error:
        print(f"Base packaging failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
