#!/usr/bin/env python3
"""Export an explicitly reviewed source allowlist into a NEW directory.

Does not publish, delete directories, copy repository history, or export images,
packages, private machine helpers, diagnostic records or credentials.
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
ALLOWLIST = (
    ".gitignore", ".gitattributes", "LICENSE", "README.md", "RELEASE.zh-CN.md",
    "WIFI-FIRSTBOOT.zh-CN.md", "KDE.zh-CN.md", "RELEASE-HYGIENE.zh-CN.md", "INSTALL.zh-CN.md",
    "ROLLING-UPGRADE.zh-CN.md", "THIRD-PARTY-LICENSES.zh-CN.md",
    "config/sources.lock.json",
    "tools/build.py", "tools/build_gpu_kmod.py", "tools/desktop.py", "tools/export_build_audit.py", "tools/export_source.py",
    "tools/flash_sd.py", "tools/image.py", "tools/package_base.py", "tools/package_bsp.py",
    "tools/package_gpu.py", "tools/package_vpu.py", "tools/personalize.py", "tools/rootfs.py", "tools/sanitize.py", "tools/sources.py",
    "runtime/a7z-boot-update", "runtime/a7z-firstboot", "runtime/a7z-firstboot.service",
    "runtime/a7z-grow-root", "runtime/a7z-grow-root.service", "runtime/a7z-install-ufs", "runtime/a7z-hdmi-compat",
    "runtime/a7z-keyring-init", "runtime/a7z-keyring-init.service",
    "runtime/boot/50-a7z-boot-snapshot.hook", "runtime/boot/99-a7z-boot-update.hook",
    "runtime/boot/cmdline", "runtime/boot/extlinux.conf.example",
    "runtime/boot/linux-radxa-a7z.preset", "runtime/boot/mkinitcpio-a7z.conf",
    "gpu/a7z-arch-xorg", "gpu/a7z-gpu-desktop.py", "gpu/a7z-gpu-probe.py", "gpu/a7z-gpu-run",
    "gpu/a7z-xorg", "gpu/capture-x11.py", "gpu/check_runtime.py", "gpu/validate-installed.py",
    "gpu/validate-userspace.sh", "gpu/README.zh-CN.md", "gpu/DESKTOP.zh-CN.md",
    "gpu/test_capture_x11.py", "gpu/test_desktop_selector.py", "gpu/test_package_gpu.py",
    "gpu/a7z-chromium", "gpu/a7z-chromium.desktop", "gpu/CHROMIUM.zh-CN.md",
    "gpu/test_chromium_launcher.py", "gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md",
    "gpu/kernel/README.md", "gpu/kernel/0001-use-generic-drm-fdinfo.patch",
    "vpu/a7z-vpu-run", "vpu/70-a7z-vpu.rules", "vpu/README.zh-CN.md",
    "vpu/CHROMIUM-INTEGRATION.zh-CN.md", "vpu/VALIDATION.zh-CN.md",
    "vpu/UPSTREAM-NOTICE.txt", "vpu/t5-sources.json", "vpu/test_package_vpu.py",
    "desktop/x11-environment.sh", "desktop/rime-default.custom.yaml", "desktop/plasma-localerc",
    "desktop/mimeapps.list", "desktop/fontconfig.conf", "desktop/fcitx5-profile",
    "desktop/fcitx5-config", "desktop/README.zh-CN.md", "desktop/HDMI.zh-CN.md", "tests/test_desktop_defaults.py",
    "desktop/xfce-a7z-chromium.desktop", "desktop/xfce-helpers.rc",
    "packages/base/LICENSE", "packages/tests/test_boot_update.py", "packages/tests/test_bsp_packager.py",
    "tests/integration_image.py", "tests/integration_personalize.py", "tests/integration_grow_root.py", "tests/test_build_safety.py",
    "tests/test_flash_sd_safety.py", "tests/test_image_safety.py", "tests/test_personalize_safety.py",
    "tests/test_rootfs_variants.py", "tests/test_sanitize.py", "tests/test_export_source.py", "tests/test_gpu_kmod_builder.py",
)

# Match actual values, not escaped pattern definitions. Findings expose only the
# fixed allowlisted filename and category, never the matched line/value.
PATTERNS = {
    "private-key-material": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "private-ipv4": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    "windows-user-path": re.compile(r"(?i)[a-z]:[\\/](?:users|documents and settings)[\\/][a-z0-9_.-]+[\\/]"),
    "literal-wifi-secret": re.compile(r"(?im)^(?:psk|password)=[A-Za-z0-9][^\r\n{}]{7,}$"),
    "embedded-public-ssh-key": re.compile(r"(?m)^\s*(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+)\s+[A-Za-z0-9+/]{80,}={0,2}(?:\s|$)"),
}


def scan_text(name, text):
    return [{"path": name, "category": category} for category, pattern in PATTERNS.items() if pattern.search(text)]


def inspect_sources(repo, allowlist=ALLOWLIST):
    repo = repo.resolve()
    payloads, missing, findings = {}, [], []
    for name in allowlist:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in payloads:
            raise ValueError("Invalid source allowlist")
        path = repo / name
        if not path.exists():
            missing.append(name)
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(repo) or not path.is_file():
            findings.append({"path": name, "category": "not-a-contained-regular-file"})
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            findings.append({"path": name, "category": "non-text-payload"})
            continue
        if b"\x00" in data or len(data) > 2 * 1024 * 1024:
            findings.append({"path": name, "category": "binary-or-oversize-payload"})
        findings.extend(scan_text(name, text))
        payloads[name] = data
    allowed = set(allowlist) | {"SOURCE-MANIFEST.json", "SHA256SUMS"}
    for name, data in payloads.items():
        if not name.endswith(".md"):
            continue
        for raw in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", data.decode()):
            link = urlsplit(raw.strip("<>"))
            if link.scheme or link.netloc or not link.path:
                continue
            resolved = ((repo / name).parent / unquote(link.path)).resolve()
            if not resolved.is_relative_to(repo) or resolved.relative_to(repo).as_posix() not in allowed:
                findings.append({"path": name, "category": "local-link-outside-source-allowlist"})
    if "config/sources.lock.json" in payloads:
        try:
            lock = json.loads(payloads["config/sources.lock.json"])
            for artifact in lock["artifacts"]:
                url = urlsplit(artifact["url"])
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query:
                    raise ValueError()
                try:
                    address = ipaddress.ip_address(url.hostname)
                except ValueError:
                    address = None
                if address is not None and not address.is_global:
                    raise ValueError()
                if not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
                    raise ValueError()
        except (KeyError, ValueError, TypeError):
            findings.append({"path": "config/sources.lock.json", "category": "unsafe-or-invalid-source-lock"})
    return payloads, {"allowlist": list(allowlist), "missing_files": missing, "findings": findings,
                      "ready": not missing and not findings}


def export(repo, output, allowlist=ALLOWLIST, plan=False):
    payloads, report = inspect_sources(repo, allowlist)
    if plan:
        return report
    if not report["ready"]:
        return report
    output = output.absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("Export requires a new directory and an existing parent; existing output is never replaced")
    output.mkdir(mode=0o755, exist_ok=False)
    records = []
    for name, data in sorted(payloads.items()):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)
        executable = data.startswith(b"#!")
        target.chmod(0o755 if executable else 0o644)
        records.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "mode": "0755" if executable else "0644"})
    manifest = {"schema": 1, "project": "cubie-a7z-archlinuxarm",
                "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "scope": "Explicitly allowlisted project source, tests, docs and upstream source lock. No images, packages, private diagnostics, backups or repository history.",
                "audit": {"result": "PASS", "categories": list(PATTERNS), "local_document_links": "within allowlist",
                          "limit": "Static checks complement the explicit allowlist; they are not a proof that arbitrary undiscovered secrets cannot exist."},
                "files": records}
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    with (output / "SOURCE-MANIFEST.json").open("xb") as handle:
        handle.write(data)
    sums = [(record["path"], record["sha256"]) for record in records]
    sums.append(("SOURCE-MANIFEST.json", hashlib.sha256(data).hexdigest()))
    with (output / "SHA256SUMS").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(f"{checksum}  {name}\n" for name, checksum in sorted(sums)))
    report.update({"exported_files": len(records), "checksummed_files": len(sums), "export_complete": True})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "out/source-release")
    parser.add_argument("--plan", "--list", action="store_true", help="review exact file list, missing inputs and safe finding categories without writing")
    args = parser.parse_args()
    try:
        report = export(REPO, args.output, plan=args.plan)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 1
    except (OSError, ValueError):
        # Do not echo arbitrary filesystem error text or source contents.
        parser.exit(1, "Source export refused; check the plan and use a new output directory with an existing parent.\n")


if __name__ == "__main__":
    raise SystemExit(main())
