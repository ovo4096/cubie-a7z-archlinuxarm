#!/usr/bin/env python3
"""Audit/sanitize an OFFLINE public image root; reports never include file contents.

The caller must exclusively own the build directory. This is a release-image
operation, not a cleanup command for an installed system. Run after the last
package transaction and after all chroot mounts have been removed.
"""
import argparse
from collections import Counter
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


EMPTY_DIRS = (
    "etc/NetworkManager/system-connections", "var/lib/NetworkManager",
    "etc/wpa_supplicant", "etc/iwd", "var/lib/iwd", "var/lib/connman",
    "var/lib/bluetooth", "etc/wireguard", "etc/openvpn", "etc/ssl/private",
    "var/lib/dhcpcd", "var/lib/dhcp", "var/lib/systemd/network",
    "var/lib/systemd/coredump", "var/lib/systemd/pstore", "var/lib/systemd/timesync",
    "var/lib/a7z", "var/lib/AccountsService/users", "var/lib/AccountsService/icons",
    "etc/pacman.d/gnupg", "var/cache", "var/log", "tmp", "var/tmp", "run",
    "mnt", "media", "config",
)
IDENTITY_FILES = (
    "var/lib/systemd/random-seed", "var/lib/systemd/credential.secret",
    "var/lib/systemd/catalog/database", "etc/hostid", "etc/adjtime",
    "var/lib/a7z/firstboot-complete", "var/lib/a7z/keyring-initialized",
    "var/lib/a7z/grow-root-complete", "var/lib/lightdm/.Xauthority",
    "var/lib/sddm/.Xauthority", "var/lib/AccountsService/users/alarm",
    "var/lib/AccountsService/icons/alarm", "etc/.pwd.lock",
)
PRIVATE_STATE_DIRS = ("var/lib/lightdm", "var/lib/sddm")
SERVICE = "a7z-keyring-init.service"
SERVICE_PATH = "usr/lib/systemd/system/" + SERVICE
SERVICE_LINK = "etc/systemd/system/multi-user.target.wants/" + SERVICE
PRIVATE_KEY = re.compile(br"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----")
PUBLIC_TOP = {"bin", "boot", "config", "dev", "etc", "home", "lib", "lib64", "lost+found",
              "media", "mnt", "opt", "proc", "root", "run", "sbin", "srv", "sys", "tmp", "usr", "var"}


class HygieneError(ValueError):
    """Intentionally static messages: never embed a discovered user pathname."""


def _mount_records():
    source = Path("/proc/self/mountinfo")
    if not source.exists():
        return []
    def unescape(text):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), text)
    result = []
    for line in source.read_text().splitlines():
        fields = line.split()
        split = fields.index("-")
        result.append({"target": Path(unescape(fields[4])), "options": fields[5].split(","),
                       "fs_type": fields[split + 1], "source": unescape(fields[split + 2])})
    return result


def _mount_targets():
    return [r["target"] for r in _mount_records()]


def validate_root(root, allow_readonly_mount=False):
    path = Path(root)
    if path.is_symlink():
        raise HygieneError("Rootfs must not be a symlink")
    root = path.resolve(strict=True)
    if root in (Path("/"), Path("/root"), Path("/home"), Path("/usr"), Path("/var")):
        raise HygieneError("Refusing a live/system root path")
    # Refuse the target itself and every nested bind mount before any deletion.
    if allow_readonly_mount:
        records = _mount_records()
        matched = [r for r in records if r["target"] == root]
        nested = any(r["target"] != root and r["target"].is_relative_to(root) for r in records)
        if (nested or len(matched) != 1 or "ro" not in matched[0]["options"]
                or matched[0]["fs_type"] != "ext4"
                or not re.fullmatch(r"/dev/loop[0-9]+(?:p[0-9]+)?", matched[0]["source"])):
            raise HygieneError("Read-only image audit requires a ro ext4 loop mount with no nested mounts")
    elif any(p == root or p.is_relative_to(root) for p in _mount_targets()):
        raise HygieneError("Rootfs contains mounted filesystems; unmount the build tree first")
    for relative in ("etc/arch-release", "usr/bin/pacman", "etc/passwd", "etc/skel"):
        target = safe_path(root, relative)
        if target.is_symlink() or not target.exists():
            raise HygieneError("Not a complete extracted Arch image root")
    return root


def safe_path(root, relative):
    """Never follow a symlink in a managed path's parents, including dangling ones."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise HygieneError("Invalid managed relative path")
    current = root
    for component in parts[:-1]:
        current /= component
        if current.is_symlink():
            raise HygieneError("Managed rootfs path has a symlink parent")
        if current.exists() and not current.is_dir():
            raise HygieneError("Managed rootfs path has a non-directory parent")
    return root / relative


def exists(path):
    return path.exists() or path.is_symlink()


def populated(path):
    return path.is_symlink() or (path.exists() and (not path.is_dir() or next(path.iterdir(), None) is not None))


def remove(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def reset_directory(path, mode=0o755):
    """Unlink leaf symlinks rather than walking their targets; retain dir ownership."""
    owner = path.stat(follow_symlinks=False) if exists(path) else None
    if path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            remove(child)
    else:
        remove(path)
        path.mkdir(parents=True, mode=mode)
    path.chmod(mode)
    if owner is not None and os.geteuid() == 0:
        os.chown(path, owner.st_uid, owner.st_gid)


def _profile_snapshot(directory):
    """Compare with packaged /etc/skel without exposing file names or contents."""
    if directory.is_symlink() or not directory.is_dir():
        return None
    result = {}
    for parent, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            p = Path(parent) / name
            key = str(p.relative_to(directory))
            if p.is_symlink():
                result[key] = ("symlink", os.readlink(p))
            elif p.is_file():
                # Compare internally in bounded memory; no digest or content
                # from a user's profile is placed in the exported report.
                digest = hashlib.sha256()
                with p.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1048576), b""):
                        digest.update(chunk)
                result[key] = ("file", p.stat().st_size, digest.digest())
            elif p.is_dir():
                result[key] = ("directory",)
            else:
                result[key] = ("special",)
    return result


def _accounts(root):
    result = []
    for line in safe_path(root, "etc/passwd").read_text().splitlines():
        fields = line.split(":")
        if len(fields) != 7:
            raise HygieneError("Invalid passwd database")
        if fields[0] in ("root", "alarm"):
            expected = "/root" if fields[0] == "root" else "/home/alarm"
            if fields[5] != expected:
                raise HygieneError("Seed account has an unexpected home directory")
            result.append((expected[1:], int(fields[2]), int(fields[3])))
        elif fields[2] == "0" or (1000 <= int(fields[2]) < 65534):
            raise HygieneError("Unexpected interactive account; review account policy before release")
    if {a[0] for a in result} != {"root", "home/alarm"}:
        raise HygieneError("Expected public seed accounts are missing")
    return result


def _keyring_prerequisites(root):
    missing = []
    for relative in ("usr/bin/a7z-keyring-init", SERVICE_PATH,
                     "usr/share/pacman/keyrings/archlinuxarm.gpg"):
        target = safe_path(root, relative)
        if target.is_symlink() or not target.is_file() or target.stat().st_size == 0:
            missing.append(relative)
    if missing:
        raise HygieneError("Install the first-boot keyring service and archlinuxarm-keyring before sanitizing")


def _password_matches(encoded):
    """Use host libcrypt (supports ALARM's yescrypt); never invoke a shell."""
    library = ctypes.util.find_library("crypt")
    if not library:
        raise HygieneError("Host libcrypt is required to verify the public seed password")
    crypt = ctypes.CDLL(library).crypt
    crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    crypt.restype = ctypes.c_char_p
    result = crypt(b"alarm", encoded.encode())
    return bool(result) and result == encoded.encode()


def _credential_policy(root):
    path = safe_path(root, "etc/shadow")
    if path.is_symlink() or not path.is_file():
        return False
    entries = {}
    for line in path.read_text().splitlines():
        parts = line.split(":")
        if len(parts) < 2 or parts[0] in entries:
            return False
        entries[parts[0]] = parts[1]
    return (entries.get("root", "").startswith(("!", "*"))
            and _password_matches(entries.get("alarm", "")))


def _check_profile_sources(root):
    """Never erase package-owned home files for which skel cannot restore defaults."""
    skel = safe_path(root, "etc/skel")
    forbidden = {".ssh", ".gnupg", ".bash_history", ".zsh_history", ".python_history", ".lesshst", "keyrings"}
    for parent, dirs, files in os.walk(skel, followlinks=False):
        if any(name in forbidden for name in dirs + files):
            raise HygieneError("Skeleton contains identity/history state; restore the packaged skeleton first")
    database = safe_path(root, "var/lib/pacman/local")
    if not database.is_dir() or database.is_symlink():
        return
    for metadata in database.glob("*/files"):
        if metadata.is_symlink() or metadata.parent.is_symlink():
            raise HygieneError("Pacman local metadata must not be symlinked")
        section = None
        for name in metadata.read_text().splitlines():
            if name.startswith("%"):
                section = name
            elif section == "%FILES%" and name and not name.endswith("/"):
                for prefix in ("root/", "home/alarm/"):
                    if name.startswith(prefix) and exists(safe_path(root, name)):
                        source = safe_path(skel, name[len(prefix):])
                        if not exists(source):
                            raise HygieneError("Package-owned home file has no skeleton default; review before cleanup")


def _plan(root):
    actions = []
    for relative in EMPTY_DIRS + PRIVATE_STATE_DIRS:
        if populated(safe_path(root, relative)):
            actions.append(("empty-directory", relative))
    for relative in IDENTITY_FILES:
        if exists(safe_path(root, relative)):
            actions.append(("remove-identity", relative))
    ssh = safe_path(root, "etc/ssh")
    if ssh.is_symlink():
        raise HygieneError("SSH configuration directory must not be a symlink")
    for p in ssh.glob("ssh_host_*"):
        actions.append(("remove-host-key", str(p.relative_to(root))))
    machine = safe_path(root, "etc/machine-id")
    if machine.is_symlink() or not machine.is_file() or machine.stat().st_size:
        actions.append(("empty-machine-id", "etc/machine-id"))
    dbus = safe_path(root, "var/lib/dbus/machine-id")
    if not dbus.is_symlink() or os.readlink(dbus) != "/etc/machine-id":
        actions.append(("link-machine-id", "var/lib/dbus/machine-id"))
    skel = _profile_snapshot(safe_path(root, "etc/skel"))
    for relative, _, _ in _accounts(root):
        if _profile_snapshot(safe_path(root, relative)) != skel:
            actions.append(("reset-home", relative))
    home = safe_path(root, "home")
    if home.is_symlink():
        raise HygieneError("Home directory must not be a symlink")
    if home.is_dir() and any(x.name != "alarm" for x in home.iterdir()):
        actions.append(("remove-other-homes", "home"))
    for p in root.iterdir():
        if p.name not in PUBLIC_TOP:
            actions.append(("remove-build-residue", p.name))
    link = safe_path(root, SERVICE_LINK)
    if not link.is_symlink() or os.readlink(link) != "/usr/lib/systemd/system/" + SERVICE:
        actions.append(("enable-keyring-service", SERVICE_LINK))
    # Validate every operation up front; an unsafe late path cannot produce a
    # partly cleaned image or make the removal cross a symlink boundary.
    for _, relative in actions:
        safe_path(root, relative)
    return actions


def _unexpected_private_keys(root):
    count = 0
    # Known private state is handled by _plan. Catch misplaced PEM keys too.
    for relative in ("etc", "opt", "srv", "usr/local"):
        base = safe_path(root, relative)
        if base.is_symlink() or not base.is_dir():
            continue
        for directory, _, files in os.walk(base, followlinks=False):
            for name in files:
                p = Path(directory) / name
                if p.is_symlink() or not p.is_file() or p.stat().st_size > 1048576:
                    continue
                with p.open("rb") as handle:
                    if PRIVATE_KEY.search(handle.read(1048576)):
                        count += 1
    return count


def audit_initramfs(root):
    """Inspect early and main CPIO; accept only a hash-free locked root shadow."""
    report = {"archives_checked": 0, "private_path_matches": 0,
              "locked_placeholder_shadow_files": 0, "inspection_errors": 0}
    for archive in safe_path(root, "boot").glob("initramfs-*.img"):
        try:
            if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 256 * 1024 * 1024:
                raise HygieneError("Initramfs is not a bounded regular file")
            data = archive.read_bytes()
            def read_archive(payload, member=None):
                arguments = ["bsdtar", "-tf", "-"] if member is None else ["bsdtar", "-xOf", "-", member]
                return subprocess.run(arguments, input=payload, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, check=True, timeout=60).stdout
            listing = read_archive(data).decode()
            offset = 0
            if data.startswith((b"070701", b"070702")) and "early_cpio" in listing.splitlines():
                # Parse newc headers; searching for TRAILER!!! in arbitrary file
                # payload can choose the wrong boundary and miss the main CPIO.
                while True:
                    header = data[offset:offset + 110]
                    if len(header) != 110 or header[:6] not in (b"070701", b"070702"):
                        raise HygieneError("Malformed early CPIO header")
                    namesize, size = int(header[94:102], 16), int(header[54:62], 16)
                    if not 1 <= namesize <= 1048576 or offset + 110 + namesize > len(data):
                        raise HygieneError("Malformed early CPIO name")
                    name = data[offset + 110:offset + 110 + namesize].rstrip(b"\0")
                    offset = (offset + 110 + namesize + 3) // 4 * 4
                    offset = (offset + size + 3) // 4 * 4
                    if offset > len(data):
                        raise HygieneError("Malformed early CPIO size")
                    if name == b"TRAILER!!!":
                        break
                offset = (offset + 511) // 512 * 512
                while offset < len(data) and data[offset] == 0:
                    offset += 512
                if offset >= len(data):
                    raise HygieneError("Main CPIO missing")
                listing += "\n" + read_archive(data[offset:]).decode()
            names = [name.removeprefix("./").rstrip("/") for name in listing.splitlines()]
            if "init" not in names:
                raise HygieneError("Main initramfs not inspected")
            sensitive = ("machine-id", "random-seed", "ssh_host_", "NetworkManager/system-connections",
                         "pacman.d/gnupg", "/.ssh/", "/.gnupg/")
            report["private_path_matches"] += sum(any(term in name for term in sensitive) for name in names)
            if "etc/shadow" in names:
                rows = [line.split(":") for line in read_archive(data[offset:], "etc/shadow").decode().splitlines() if line]
                harmless = (len(rows) == 1 and len(rows[0]) >= 2 and rows[0][0] == "root"
                            and bool(rows[0][1]) and set(rows[0][1]) <= {"!", "*"})
                report["locked_placeholder_shadow_files" if harmless else "private_path_matches"] += 1
            report["archives_checked"] += 1
        except (OSError, ValueError, subprocess.SubprocessError):
            report["inspection_errors"] += 1
    report["clean"] = report["private_path_matches"] == report["inspection_errors"] == 0
    return report


def audit_root(root, allow_readonly_mount=False):
    """Return a redacted public-release report; does not modify root."""
    root = validate_root(root, allow_readonly_mount=allow_readonly_mount)
    actions = _plan(root)
    blockers = []
    try:
        _keyring_prerequisites(root)
    except HygieneError:
        blockers.append("firstboot-keyring-prerequisites-missing")
    if not _credential_policy(root):
        blockers.append("public-password-policy-mismatch")
    try:
        _check_profile_sources(root)
    except HygieneError:
        blockers.append("profile-defaults-require-review")
    misplaced = _unexpected_private_keys(root)
    if misplaced:
        blockers.append("private-key-material-present")
    initramfs = audit_initramfs(root)
    if not initramfs["clean"]:
        blockers.append("initramfs-identity-review-required")
    categories = dict(sorted(Counter(action for action, _ in actions).items()))
    return {"schema": 1, "kind": "public-rootfs-hygiene", "clean": not actions and not blockers,
            "pending_actions": len(actions), "action_categories": categories,
            "blockers": blockers, "private_key_files_detected": misplaced,
            "initramfs": initramfs,
            "scope": "Offline rootfs only; image partitions and release output require separate checks",
            "password_policy": "Root must be locked; alarm must match the documented public alarm password; hashes are never exported"}


def sanitize_root(root, apply=False):
    """Default dry run. Apply is idempotent and never traverses managed symlinks."""
    root = validate_root(root)
    before = audit_root(root)
    if not apply:
        return {"applied": False, "before": before, "after": None}
    _keyring_prerequisites(root)
    _check_profile_sources(root)
    if not _credential_policy(root):
        raise HygieneError("Restore documented public credentials before sanitizing")
    accounts = {name: (uid, gid) for name, uid, gid in _accounts(root)}
    actions = _plan(root)
    for action, relative in actions:
        path = safe_path(root, relative)
        if action == "empty-directory":
            mode = 0o700 if relative in ("etc/pacman.d/gnupg", "etc/NetworkManager/system-connections") else 0o755
            if relative in ("tmp", "var/tmp"):
                mode = 0o1777
            reset_directory(path, mode)
        elif action in ("remove-identity", "remove-host-key", "remove-build-residue"):
            remove(path)
        elif action == "empty-machine-id":
            remove(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o444)
        elif action in ("link-machine-id", "enable-keyring-service"):
            remove(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to("/etc/machine-id" if action == "link-machine-id" else "/usr/lib/systemd/system/" + SERVICE)
        elif action == "reset-home":
            remove(path)
            shutil.copytree(safe_path(root, "etc/skel"), path, symlinks=True)
            path.chmod(0o700 if relative == "root" else 0o755)
            if os.geteuid() == 0:
                uid, gid = accounts[relative]
                os.chown(path, uid, gid)
                for directory, dirs, files in os.walk(path, followlinks=False):
                    for name in dirs + files:
                        os.chown(Path(directory) / name, uid, gid, follow_symlinks=False)
        elif action == "remove-other-homes":
            for child in path.iterdir():
                if child.name != "alarm":
                    remove(child)
    after = audit_root(root)
    return {"applied": True, "before": before, "after": after}


def audit_output(output):
    """Inspect release metadata and private evidence names; opaque images are not opened."""
    output = Path(output).resolve(strict=True)
    if not output.is_dir():
        raise HygieneError("Release output must be a directory")
    findings = Counter()
    opaque = 0
    banned = {"backups", "diagnostics", "logs", "initial-candidate", "pre-installer-fix-candidate", ".ssh", ".gnupg"}
    for directory, dirs, files in os.walk(output, followlinks=False):
        for name in dirs + files:
            p = Path(directory) / name
            parts = p.relative_to(output).parts
            if p.is_symlink():
                findings["symlink-in-release"] += 1
            if any(part.lower() in banned for part in parts) or name == "BOARD-AUDIT.zh-CN.md":
                findings["private-audit-or-build-evidence"] += 1
            if "-private" in name.lower() or name in ("ssh-authorized-keys", "hostname", "PRIVATE-IMAGE.txt", "a7z-private-seed.json") or name.endswith(".nmconnection"):
                findings["private-seed-or-image"] += 1
            if p.is_symlink() or not p.is_file():
                continue
            if name.endswith((".img", ".img.zst", ".pkg.tar.zst")):
                opaque += 1
                continue
            if p.stat().st_size <= 4 * 1024 * 1024:
                contents = p.read_bytes()
                if PRIVATE_KEY.search(contents):
                    findings["private-key-material"] += 1
                if name.endswith(".json"):
                    try:
                        document = json.loads(contents)
                    except (ValueError, UnicodeError):
                        findings["invalid-json-metadata"] += 1
                    else:
                        def has_private_seed(node):
                            if isinstance(node, dict):
                                return bool(node.get("private_seed_included")) or any(has_private_seed(v) for v in node.values())
                            return isinstance(node, list) and any(has_private_seed(v) for v in node)
                        if has_private_seed(document):
                            findings["private-seed-declared-in-metadata"] += 1
    return {"schema": 1, "kind": "public-output-hygiene", "clean": not findings,
            "findings": dict(sorted(findings.items())), "opaque_artifacts_not_inspected": opaque,
            "scope": "No image/package contents examined; require a clean source-root report and image config partition audit"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path)
    parser.add_argument("--output-dir", type=Path, help="Read-only public release directory audit")
    parser.add_argument("--apply", action="store_true", help="Sanitize the offline rootfs; never modifies output artifacts")
    parser.add_argument("--readonly-image-audit", action="store_true", help="Audit an actual ro ext4 loop-mounted root partition; no nested mounts")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.rootfs and not args.output_dir:
        parser.error("Provide --rootfs and/or --output-dir")
    if args.apply and (not args.rootfs or sys.platform != "linux" or os.geteuid() != 0):
        parser.error("--apply requires an offline rootfs and Linux root")
    if args.readonly_image_audit and (args.apply or not args.rootfs):
        parser.error("--readonly-image-audit requires --rootfs and is incompatible with --apply")
    try:
        report = {}
        if args.rootfs:
            report["rootfs"] = ({"applied": False, "before": audit_root(args.rootfs, allow_readonly_mount=True), "after": None}
                                if args.readonly_image_audit else sanitize_root(args.rootfs, args.apply))
        if args.output_dir:
            report["output"] = audit_output(args.output_dir)
        rendered = json.dumps(report, indent=2) + "\n"
        if args.report:
            # Keep reports outside the cleaned image and reject existing symlinks.
            if args.report.is_symlink() or (args.rootfs and args.report.resolve().is_relative_to(args.rootfs.resolve())):
                raise HygieneError("Write the report outside the rootfs to a regular output path")
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered)
        print(rendered, end="")
        clean = all((value.get("after") or value.get("before") or value)["clean"] for value in report.values())
        return 0 if clean else 2
    except (OSError, ValueError):
        # An OS exception can contain a credential-bearing file name. The fixed
        # error does not; inspect the build tree locally if detailed review is needed.
        print("Hygiene check refused: invalid/offline-root safety or prerequisite check failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
