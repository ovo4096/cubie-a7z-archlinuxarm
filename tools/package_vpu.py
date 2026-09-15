#!/usr/bin/env python3
"""Repackage pinned T5 Cedar/OMX files as an opt-in, isolated Arch package."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

try:
    from . import package_gpu as helper
except ImportError:
    import package_gpu as helper

REPO = Path(__file__).resolve().parents[1]
NAME = 'radxa-a7z-vpu'
VERSION = '0.1.0-3'
PRIVATE = 'usr/lib/radxa-a7z-vpu'
SHARE = 'usr/share/radxa-a7z-vpu'
LICENSES = 'usr/share/licenses/radxa-a7z-vpu'
PACKAGES = {'libcedarc-dev-2.0.0-arm64': '1.0.7',
            'gstreamer1.0-omx-allwinner': '1.18.3-1.1',
            'gstreamer1.0-omx-allwinner-config': '1.18.3-1.1'}
DEPS = ['glibc', 'bash', 'coreutils', 'systemd', 'linux-radxa-a7z=6.6.98_4-2',
        'gstreamer', 'gst-plugins-base', 'gst-plugins-good', 'gst-plugins-bad']
SOURCE_URL = 'https://github.com/radxa-build/radxa-a733/releases/tag/rsdk-t5'


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def safe_relative(value: str) -> str:
    if (not value or value.startswith('/') or '\\' in value or '\x00' in value or
            any(ord(c) < 32 for c in value) or '..' in PurePosixPath(value).parts):
        raise ValueError(f'Unsafe package path: {value!r}')
    if str(PurePosixPath(value)) != value:
        raise ValueError(f'Non-canonical package path: {value!r}')
    return value


def destination_allowed(value: str) -> bool:
    safe_relative(value)
    return any(value.startswith(prefix + '/') for prefix in (PRIVATE, SHARE, LICENSES))


def verify_sources(root: Path, pins: dict) -> list[dict]:
    if pins.get('schema') != 1 or pins.get('vendor_release') != 'rsdk-t5':
        raise ValueError('Expected fixed T5 source pins')
    if {k: v.get('version') for k, v in pins['packages'].items()} != PACKAGES:
        raise ValueError('Unexpected pinned source package versions')
    for package, version in PACKAGES.items():
        if helper.dpkg_version(root, package) != version:
            raise ValueError(f'T5 source version mismatch: {package}')
        path = helper.rooted(root, f'var/lib/dpkg/info/{package}.list')
        if helper.sha256(path) != pins['packages'][package]['dpkg_list_sha256']:
            raise ValueError(f'T5 installed-file list changed: {package}')
    rows = []
    destinations = set()
    for record in pins['files']:
        source = safe_relative(record['source'])
        destination = safe_relative(record['destination'])
        if record['package'] not in PACKAGES or not destination_allowed(destination):
            raise ValueError(f'Unexpected VPU payload: {record}')
        if destination in destinations:
            raise ValueError(f'Duplicate destination: {destination}')
        destinations.add(destination)
        path = helper.rooted(root, source)
        if not path.is_file() or path.is_symlink() or not path.is_relative_to(root):
            raise ValueError(f'Not an isolated regular source file: {source}')
        digest = helper.sha256(path)
        if digest != record['sha256']:
            raise ValueError(f'Upstream file hash changed: {source}')
        rows.append(dict(record, path=path))
    required = {f'{PRIVATE}/lib/libOmxCore.so', f'{PRIVATE}/lib/libvdecoder.so',
                f'{PRIVATE}/lib/libMemAdapter.so', f'{PRIVATE}/lib/libVE.so',
                f'{PRIVATE}/gstreamer-1.0/libgstomx.so', f'{SHARE}/gstomx.conf'}
    if not required <= destinations:
        raise ValueError('Pinned payload lacks required Cedar/OMX components')
    return rows


def archive(stage: Path, output: Path, epoch: int) -> Path:
    """Deterministic tar/mtree metadata, following package_bsp.py's archive format."""
    entries = {}
    for path in sorted(stage.rglob('*')):
        name = safe_relative(path.relative_to(stage).as_posix())
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f'Unexpected staged file type: {name}')
        entries[name] = {'path': path, 'directory': path.is_dir(),
                         'mode': 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644}
    size = sum(x['path'].stat().st_size for x in entries.values() if not x['directory'])
    metadata = [f'pkgname = {NAME}', f'pkgbase = {NAME}', f'pkgver = {VERSION}',
                'pkgdesc = Radxa A7Z T5 isolated Cedar/OMX video userspace (optional)',
                f'url = {SOURCE_URL}', f'builddate = {epoch}',
                'packager = Cubie A7Z Arch Linux ARM port', f'size = {size}', 'arch = aarch64',
                'license = custom:vendor-see-UPSTREAM-NOTICE']
    metadata.extend('depend = ' + x for x in DEPS)
    info = ('\n'.join(metadata) + '\n').encode()
    entries['.PKGINFO'] = {'data': info, 'directory': False, 'mode': 0o644}
    mtree = ['#mtree', f'/set uid=0 gid=0 time={epoch}']
    for name, row in sorted(entries.items()):
        escaped = ''.join(f'\\{ord(x):03o}' if x in ' \\#\t\n' else x for x in name)
        line = f'./{escaped} type={"dir" if row["directory"] else "file"} mode={row["mode"]:o}'
        if not row['directory']:
            data = row.get('data')
            if data is None:
                data = row['path'].read_bytes()
            line += f' size={len(data)} sha256digest={hashlib.sha256(data).hexdigest()}'
        mtree.append(line)
    entries['.MTREE'] = {'data': gzip.compress(('\n'.join(mtree) + '\n').encode(), mtime=0),
                         'directory': False, 'mode': 0o644}
    target = output / f'{NAME}-{VERSION}-aarch64.pkg.tar.zst'
    if target.exists():
        raise ValueError(f'Refusing to replace existing package: {target}')
    with tempfile.TemporaryDirectory(prefix='vpu-archive-', dir=output) as temp:
        raw = Path(temp) / 'package.tar'
        with tarfile.open(raw, 'w', format=tarfile.GNU_FORMAT) as tar:
            for name, row in sorted(entries.items()):
                item = tarfile.TarInfo(name + ('/' if row['directory'] else ''))
                item.uid = item.gid = 0
                item.uname = item.gname = 'root'
                item.mtime, item.mode = epoch, row['mode']
                if row['directory']:
                    item.type = tarfile.DIRTYPE
                    tar.addfile(item)
                else:
                    data = row.get('data')
                    if data is None:
                        data = row['path'].read_bytes()
                    item.size = len(data)
                    tar.addfile(item, io.BytesIO(data))
        compressed = Path(temp) / target.name
        subprocess.run(['zstd', '-q', '-T1', '-19', str(raw), '-o', str(compressed)], check=True)
        os.replace(compressed, target)
    return target


def build(vendor: Path, output: Path) -> dict:
    root, output = vendor.resolve(), output.resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError('Output must be outside the vendor rootfs')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output directory must be new or empty')
    pins_file = REPO / 'vpu/t5-sources.json'
    pins = json.loads(pins_file.read_text())
    rows = verify_sources(root, pins)
    for tool in ('readelf', 'patchelf', 'zstd'):
        if not shutil.which(tool):
            raise ValueError(f'Missing host tool: {tool}')
    output.mkdir(parents=True, exist_ok=True)
    provenance = {'schema': 1, 'package': NAME, 'version': VERSION,
                  'vendor_release': SOURCE_URL, 'rootfs_sha256': pins['rootfs_sha256'],
                  'source_packages': PACKAGES, 'source_date_epoch': pins['source_date_epoch'],
                  'method': 'isolated binary repackage; no maintainer scripts or installation',
                  'files': [], 'recipe_files': {}}
    with tempfile.TemporaryDirectory(prefix='a7z-vpu-stage-') as temp:
        stage = Path(temp)
        for row in rows:
            target = stage / row['destination']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['path'], target)
            target.chmod(0o644)
            record = {key: value for key, value in row.items() if key != 'path'}
            if helper.is_elf(target):
                info = helper.elf_info(target)
                if not info['aarch64']:
                    raise ValueError(f'Non-AArch64 VPU object: {row["source"]}')
                record['needed'] = info['needed']
                record['upstream_rpath'] = info['rpath']
                rpath = '$ORIGIN' if '/lib/' in row['destination'] and '/gstreamer-1.0/' not in row['destination'] and '/bin/' not in row['destination'] else '$ORIGIN/../lib'
                subprocess.run(['patchelf', '--set-rpath', rpath, str(target)], check=True)
                if '/bin/' in row['destination']:
                    target.chmod(0o755)
                assert helper.elf_info(target)['rpath'] == [rpath]
            elif row['destination'] == f'{SHARE}/gstomx.conf':
                old = '/usr/lib/aarch64-linux-gnu/libOmxCore.so'
                value = target.read_text()
                if old not in value:
                    raise ValueError('Unexpected upstream OMX core configuration')
                target.write_text(value.replace(old, f'/{PRIVATE}/lib/libOmxCore.so'))
            record['packaged_sha256'] = helper.sha256(target)
            provenance['files'].append(record)
        generated = {'vpu/a7z-vpu-run': 'usr/bin/a7z-vpu-run',
                     'vpu/70-a7z-vpu.rules': 'usr/lib/udev/rules.d/70-a7z-vpu.rules',
                     'vpu/UPSTREAM-NOTICE.txt': f'{LICENSES}/UPSTREAM-NOTICE.txt',
                     'vpu/README.zh-CN.md': f'usr/share/doc/{NAME}/README.zh-CN.md',
                     'vpu/VALIDATION.zh-CN.md': f'usr/share/doc/{NAME}/VALIDATION.zh-CN.md',
                     'vpu/CHROMIUM-INTEGRATION.zh-CN.md': f'usr/share/doc/{NAME}/CHROMIUM-INTEGRATION.zh-CN.md'}
        for source, destination in generated.items():
            path = REPO / source
            target = stage / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o755 if destination.startswith('usr/bin/') else 0o644)
            provenance['recipe_files'][source] = helper.sha256(path)
        for source in ('tools/package_vpu.py', 'tools/package_gpu.py', 'vpu/t5-sources.json'):
            provenance['recipe_files'][source] = helper.sha256(REPO / source)
        (stage / f'usr/share/doc/{NAME}/vpu-provenance.json').write_bytes(json_bytes(provenance))
        result = archive(stage, output, pins['source_date_epoch'])
    summary = {'name': NAME, 'version': VERSION, 'filename': result.name,
               'bytes': result.stat().st_size, 'sha256': helper.sha256(result),
               'source_files': len(rows), 'installed': False,
               'hardware_validation': 'requires validation of this packaged artifact'}
    (output / 'vpu-provenance.json').write_bytes(json_bytes(provenance))
    (output / 'vpu-manifest.json').write_bytes(json_bytes(summary))
    (output / 'SHA256SUMS.vpu').write_text(f'{summary["sha256"]}  {result.name}\n')
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vendor-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    try:
        print(json.dumps(build(args.vendor_root, args.output), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        ap.exit(1, f'error: {exc}\n')


if __name__ == '__main__':
    main()
