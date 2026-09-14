#!/usr/bin/python3
"""Write and fully verify a reviewed 512-sector image to an identified, idle SD card.

Default is read-only. --apply requires the exact card CID and the image hash.
This tool never selects a device automatically; use lsblk and inspect its contents first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(handle, length=None):
    result = hashlib.sha256()
    while length is None or length > 0:
        block = handle.read(8 * 1024 * 1024 if length is None else min(length, 8 * 1024 * 1024))
        if not block:
            if length:
                raise ValueError('Unexpected end while reading')
            break
        result.update(block)
        if length is not None:
            length -= len(block)
    return result.hexdigest()


def inspect(target, cid, size):
    if not re.fullmatch(r'/dev/mmcblk[0-9]+', str(target)) or not stat.S_ISBLK(target.stat().st_mode):
        raise ValueError('Target must be an explicit whole MMC/SD device')
    sysfs = Path('/sys/class/block') / target.name
    if (sysfs / 'device/type').read_text().strip() != 'SD':
        raise ValueError('Refusing a non-SD MMC device')
    if (sysfs / 'device/cid').read_text().strip().lower() != cid.lower():
        raise ValueError('Card CID changed or does not match the reviewed card')
    if int(output('blockdev', '--getss', str(target))) != 512:
        raise ValueError('This is not a 512-byte logical-sector SD card')
    if int(output('blockdev', '--getsize64', str(target))) < size:
        raise ValueError('Image exceeds SD capacity')
    devices = json.loads(output('lsblk', '-J', '-p', '-o', 'NAME,MOUNTPOINTS', str(target)))['blockdevices']
    pending = list(devices)
    names = []
    while pending:
        item = pending.pop()
        names.append(item['name'])
        if any(item.get('mountpoints') or []):
            raise ValueError('Target or a child is mounted/in use')
        pending.extend(item.get('children', []))
        node = Path('/sys/class/block') / Path(item['name']).name
        if list((node / 'holders').iterdir()):
            raise ValueError('Target has an active device-mapper/RAID holder')
    swaps = Path('/proc/swaps').read_text().splitlines()[1:]
    if any(line.split()[0] in names for line in swaps):
        raise ValueError('Target contains active swap')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--cid', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run on Linux as root')
    if not re.fullmatch('[0-9a-fA-F]{64}', args.sha256):
        parser.error('Expected a SHA256 hex digest')
    if args.image.is_symlink() or not args.image.is_file():
        parser.error('Image must be a regular file')
    target = args.target.resolve(strict=True)
    size = args.image.stat().st_size
    with args.image.open('rb') as source:
        original_stat = os.fstat(source.fileno())
        source.seek(512)
        if source.read(8) != b'EFI PART':
            raise ValueError('Image lacks GPT at 512-byte LBA 1')
        source.seek(0)
        if digest(source) != args.sha256.lower():
            raise ValueError('Source image checksum mismatch')
        inspect(target, args.cid, size)
        print(json.dumps({'target': str(target), 'cid': args.cid, 'image_bytes': size,
                          'sha256': args.sha256, 'apply': args.apply}), flush=True)
        if not args.apply:
            return
        source.seek(0)
        # O_EXCL on a Linux whole block device rejects active mounts and open holders.
        descriptor = os.open(target, os.O_RDWR | os.O_EXCL)
        with os.fdopen(descriptor, 'r+b', buffering=0) as destination:
            inspect(target, args.cid, size)
            copied = 0
            written_hash = hashlib.sha256()
            while copied < size:
                block = source.read(min(size - copied, 8 * 1024 * 1024))
                if not block:
                    raise ValueError('Source was truncated while writing')
                written_hash.update(block)
                view = memoryview(block)
                while view:
                    written = destination.write(view)
                    if not written:
                        raise OSError('Short SD write')
                    view = view[written:]
                copied += len(block)
                if copied % (256 * 1024 * 1024) == 0:
                    print(f'Written {copied}/{size} bytes', flush=True)
            current_stat = os.fstat(source.fileno())
            if ((current_stat.st_size, current_stat.st_mtime_ns) !=
                    (original_stat.st_size, original_stat.st_mtime_ns) or
                    written_hash.hexdigest() != args.sha256.lower()):
                raise ValueError('Source changed during writing; do not boot this SD')
            os.fsync(destination.fileno())
            # Evict cached data before full readback verification.
            subprocess.run(['blockdev', '--flushbufs', str(target)], check=True)
            destination.seek(0)
            if digest(destination, size) != args.sha256.lower():
                raise ValueError('SD full readback checksum mismatch')
        subprocess.run(['blockdev', '--rereadpt', str(target)], check=True)
        print('SD image verified byte-for-byte. GPT/root expansion occurs on first boot.')


if __name__ == '__main__':
    main()
