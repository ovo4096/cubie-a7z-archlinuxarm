#!/usr/bin/env python3
"""Create a PRIVATE, Wi-Fi-seeded copy of a pristine A7Z SD/UFS .img.

Linux needs mtools; Windows dispatches to WSL Ubuntu. No mounts, root privilege,
loop devices or physical disks are used. Passwords are never command arguments.
"""
import argparse
import getpass
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
import warnings

REPO = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("a7z_ufs_format", str(REPO / "runtime/a7z-install-ufs"))
spec = importlib.util.spec_from_loader(loader.name, loader)
ufs = importlib.util.module_from_spec(spec)
loader.exec_module(ufs)
MIB = 1024 * 1024


def regular_open(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("Only regular files are accepted; devices are forbidden")
    return os.fdopen(descriptor, "rb")


def inspect(handle):
    size = os.fstat(handle.fileno()).st_size
    handle.seek(0)
    mbr = handle.read(512)
    if len(mbr) != 512 or mbr[510:] != b"\x55\xaa" or mbr[450] != 0xEE:
        raise ValueError("Missing protective MBR")
    matches = []
    for sector in (512, 4096):
        handle.seek(sector)
        if handle.read(8) == b"EFI PART":
            matches.append(sector)
    if len(matches) != 1:
        raise ValueError("Expected one unambiguous 512/4096 GPT layout")
    sector = matches[0]
    if size % sector:
        raise ValueError("Image size is not a whole number of sectors")
    sectors = size // sector
    header = ufs.gpt_header(handle, sector, 1)
    backup = ufs.gpt_header(handle, sector, sectors - 1)
    table_sectors = (len(header["entries_raw"]) + sector - 1) // sector
    if (header["entries_lba"] != 2 or header["backup"] != sectors - 1 or
            backup["backup"] != 1 or backup["entries_lba"] != sectors - 1 - table_sectors or
            header["disk_guid"] != backup["disk_guid"] or
            header["entries_raw"] != backup["entries_raw"] or
            header["first"] != backup["first"] or header["last"] != backup["last"] or
            not 2 + table_sectors <= header["first"] <= 32768 or
            not header["first"] <= header["last"] < backup["entries_lba"]):
        raise ValueError("GPT bounds, tables or backup disagree")
    parts = header["partitions"]
    root_start = 679936 if sector == 512 else 142336
    expected = [(32768, 65535, "config", ufs.LINUX_TYPE),
                (65536, root_start - 1, "efi", ufs.EFI_TYPE),
                (root_start, None, "rootfs", ufs.LINUX_TYPE)]
    if [p["number"] for p in parts] != [1, 2, 3] or len({p["uuid"] for p in parts}) != 3:
        raise ValueError("Expected three distinct T5 partitions")
    for part, (start, end, name, kind) in zip(parts, expected):
        if (part["start"] != start or (end is not None and part["end"] != end) or
                part["name"] != name or part["type"] != kind or
                not header["first"] <= start <= part["end"] <= header["last"] or
                (name != "config" and not part["attributes"] & 4)):
            raise ValueError("Image does not match the pinned T5 partition geometry")
    if parts[2]["end"] - root_start + 1 < 256 * MIB // sector:
        raise ValueError("Implausibly small root partition")
    handle.seek(root_start * sector + 1024)
    ext = handle.read(1024)
    if ext[56:58] != b"\x53\xef":
        raise ValueError("Root filesystem is not ext4")
    offset, length = 32768 * sector, 32768 * sector
    handle.seek(offset)
    fat = handle.read(512)
    total = struct.unpack_from("<H", fat, 19)[0] or struct.unpack_from("<I", fat, 32)[0]
    # dosfstools may round the filesystem down to complete CHS tracks. The
    # official loop-device formatting can leave e.g. eight unused 512-byte
    # sectors at the partition tail; they remain outside the FAT volume.
    fat_bytes = total * sector
    if (fat[510:512] != b"\x55\xaa" or struct.unpack_from("<H", fat, 11)[0] != sector or
            not length - MIB <= fat_bytes <= length):
        raise ValueError("Config FAT volume bounds do not match GPT")
    return {"sector_size": sector, "disk_bytes": size, "disk_guid": header["disk_guid"],
            "partitions": parts, "root_uuid": str(uuid.UUID(bytes=ext[104:120])),
            "config_offset": offset, "config_bytes": length}


def wifi_profile(ssid, password, hidden=False):
    encoded = ssid.encode("utf-8")
    if not 1 <= len(encoded) <= 32 or "\0" in ssid:
        raise ValueError("SSID must contain 1..32 UTF-8 bytes without NUL")
    if re.fullmatch(r"[0-9a-fA-F]{64}", password):
        psk = password.lower()
    elif 8 <= len(password) <= 63 and all(32 <= ord(char) <= 126 for char in password):
        psk = hashlib.pbkdf2_hmac("sha1", password.encode("ascii"), encoded, 4096, 32).hex()
    else:
        raise ValueError("WPA2 password must be 8..63 printable ASCII characters or a 64-digit hexadecimal PSK")
    # Numeric SSID representation avoids keyfile escapes and supports Unicode SSIDs.
    return (f"[connection]\nid=a7z-headless\nuuid={uuid.uuid4()}\ntype=wifi\nautoconnect=true\n\n"
            "[wifi]\nmode=infrastructure\nssid=" + ";".join(str(x) for x in encoded) + ";\n" +
            f"hidden={'true' if hidden else 'false'}\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={psk}\npsk-flags=0\n\n"
            "[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n").encode()


def hostname_text(value):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise ValueError("Hostname must be a single lowercase DNS label (1..63 characters)")
    return (value + "\n").encode()


def read_password(args):
    if args.password_file:
        with regular_open(args.password_file) as handle:
            info = os.fstat(handle.fileno())
            if info.st_uid not in (os.getuid(), 0) or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("Password file must be owned by this user/root and have mode 0600 or stricter; use a WSL-native file")
            raw = handle.read(257)
        if len(raw) > 256:
            raise ValueError("Password file is too large")
        password = raw.decode("utf-8").removesuffix("\n").removesuffix("\r")
    elif args.password_stdin:
        password = sys.stdin.read(257).removesuffix("\n")
    else:
        # Fail rather than falling back to an echoing stdin prompt.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Wi-Fi password (hidden): ")
    if "\n" in password or "\r" in password or "\0" in password:
        raise ValueError("Password must be one line")
    return password


def mtool(command, fat, *arguments, input=None):
    environment = dict(os.environ, MTOOLSRC="/dev/null", LC_ALL="C")
    result = subprocess.run([command, "-i", str(fat), *arguments], input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    if result.returncode:
        # Tool output may contain profile contents. Deliberately do not relay it.
        raise ValueError(f"{command} failed while accessing the isolated config partition")
    return result.stdout


def personalize(args, password):
    for command in ("mcopy", "mdir", "mmd"):
        if not shutil.which(command):
            raise ValueError("Install mtools before personalizing an image")
    source = Path(args.image).absolute()
    target = Path(args.output).absolute()
    if target.suffix != ".img" or "-private" not in target.stem:
        raise ValueError("Private output must be named *-private*.img")
    if target.exists() or target.is_symlink() or target.resolve() == source.resolve():
        raise ValueError("Output must be a new file distinct from the source")
    if not target.parent.is_dir():
        raise ValueError("Output parent directory must already exist")
    for suffix in (".json", ".sha256"):
        if Path(str(target) + suffix).exists() or Path(str(target) + suffix).is_symlink():
            raise ValueError("Output sidecar already exists")
    profile = wifi_profile(args.ssid, password, args.hidden)
    host = hostname_text(args.hostname) if args.hostname else None
    keys = None
    if args.ssh_key:
        with regular_open(args.ssh_key) as keyfile:
            keys = keyfile.read(1024 * 1024 + 1)
        if not keys or len(keys) > 1024 * 1024 or b"PRIVATE KEY" in keys:
            raise ValueError("SSH input must contain public keys, at most 1 MiB")
        for line in keys.decode("utf-8").splitlines():
            if line.strip() and not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,2}(?: [^\r\n]*)?", line):
                raise ValueError("SSH key file must contain plain OpenSSH public-key lines")
    expected = ufs.expected_digest(source, args.sha256)
    with regular_open(source) as original, tempfile.TemporaryDirectory(prefix=".a7z-private-", dir=target.parent) as work_name:
        work = Path(work_name)
        before = os.fstat(original.fileno())
        layout = inspect(original)
        private = work / "private.partial"
        digest = hashlib.sha256()
        original.seek(0)
        with private.open("xb") as output:
            os.chmod(private, 0o600)
            remaining = before.st_size
            while remaining:
                chunk = original.read(min(8 * MIB, remaining))
                if not chunk:
                    raise ValueError("Source image became shorter during copying")
                output.write(chunk); digest.update(chunk); remaining -= len(chunk)
            if original.read(1):
                raise ValueError("Source image grew during copying")
        after = os.fstat(original.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest.hexdigest() != expected:
            raise ValueError("Source image changed or failed its SHA256 check")
        # Work on an isolated FAT file. Even malformed FAT metadata cannot reach
        # the bootloader, EFI/rootfs partitions, source image or any device.
        with tempfile.TemporaryDirectory(prefix="a7z-private-fat-") as fat_work:
            fat = Path(fat_work) / "config.fat"
            original.seek(layout["config_offset"])
            fat.write_bytes(original.read(layout["config_bytes"]))
            os.chmod(fat, 0o600)
            listing = mtool("mdir", fat, "-b", "::/").decode("utf-8", errors="replace").lower()
            if any(name in listing for name in ("/wifi", "ssh-authorized-keys", "hostname", "private", "a7z-private-seed")):
                raise ValueError("Input already contains seed/private files; use a pristine public image")
            metadata = json.loads(mtool("mcopy", fat, "::/a7z-image.json", "-"))
            if metadata.get("private_seed_included", False) or metadata.get("sector_size") != layout["sector_size"]:
                raise ValueError("Input manifest is private or disagrees with GPT")
            marker = {"schema": 1, "private_seed_included": True, "source_sha256": expected,
                      "cleanup_after_import": True}
            mtool("mmd", fat, "::/wifi")
            mtool("mcopy", fat, "-", "::/wifi/a7z-headless.nmconnection", input=profile)
            if keys:
                mtool("mcopy", fat, "-", "::/ssh-authorized-keys", input=keys)
            if host:
                mtool("mcopy", fat, "-", "::/hostname", input=host)
            mtool("mcopy", fat, "-", "::/a7z-private-seed.json", input=(json.dumps(marker) + "\n").encode())
            mtool("mcopy", fat, "-", "::/PRIVATE-IMAGE.txt", input=b"PRIVATE IMAGE: contains network credentials. Do not publish or share.\n")
            metadata["private_seed_included"] = True
            mtool("mcopy", fat, "-o", "-", "::/a7z-image.json", input=(json.dumps(metadata, indent=2) + "\n").encode())
            if mtool("mcopy", fat, "::/wifi/a7z-headless.nmconnection", "-") != profile:
                raise ValueError("Private profile read-back failed")
            if fat.stat().st_size != layout["config_bytes"]:
                raise ValueError("Config partition size changed")
            with private.open("r+b") as output:
                output.seek(layout["config_offset"])
                output.write(fat.read_bytes()); output.flush(); os.fsync(output.fileno())
        with private.open("rb") as handle:
            if inspect(handle) != layout:
                raise ValueError("Private image GPT/filesystem geometry changed")
        metadata.update({"private_seed_included": True, "source_sha256": expected,
                         "sha256": ufs.digest_file(private), "disk_bytes": layout["disk_bytes"],
                         "personalization": "Wi-Fi seed; optional SSH public key/hostname; no credentials logged"})
        os.link(private, target)  # atomic no-replace publication, same filesystem
        for suffix, content in ((".json", json.dumps(metadata, indent=2) + "\n"),
                                (".sha256", f"{metadata['sha256']}  {target.name}\n")):
            descriptor = os.open(str(target) + suffix, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(content)
    print(f"Created PRIVATE image: {target}\nDo not publish this image. Source image was not modified.")


def windows_dispatch(args):
    def translate(value):
        if re.match(r"^[A-Za-z]:[\\/]", value):
            return subprocess.check_output(["wsl.exe", "-d", args.wsl_distribution, "--exec", "wslpath", "-a", value.replace("\\", "/")], text=True).strip()
        return value
    script = translate(str(Path(__file__).resolve()))
    forwarded = [translate(x) for x in sys.argv[1:]]
    command = ["wsl.exe", "-d", args.wsl_distribution, "--exec", "python3", script, *forwarded]
    if args.password_file:
        return subprocess.call(command)
    password = read_password(args)
    # A pipe transports the hidden password; process argv/environment omit it.
    return subprocess.run([*command, "--password-stdin"], input=password + "\n", text=True).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="pristine uncompressed public .img; matching .sha256 required")
    parser.add_argument("--output", required=True, help="new *-private*.img file")
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--hidden", action="store_true", help="network does not broadcast its SSID")
    parser.add_argument("--password-file", help="one-line file on Linux/WSL, owner-only permissions")
    parser.add_argument("--password-stdin", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sha256", help="expected source SHA256 instead of a sidecar")
    parser.add_argument("--ssh-key", help="optional plain OpenSSH public-key file")
    parser.add_argument("--hostname", help="optional lowercase DNS hostname label")
    parser.add_argument("--wsl-distribution", default="Ubuntu")
    args = parser.parse_args()
    try:
        if args.password_file and args.password_stdin:
            raise ValueError("Choose one password input method")
        if sys.platform == "win32":
            return windows_dispatch(args)
        if sys.platform != "linux":
            raise ValueError("Use Linux or WSL on Windows")
        personalize(args, read_password(args))
        return 0
    except (OSError, ValueError, UnicodeError, getpass.GetPassWarning, subprocess.SubprocessError) as exc:
        # Exceptions are intentionally authored without any secret values.
        parser.exit(1, f"Personalization refused/failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
