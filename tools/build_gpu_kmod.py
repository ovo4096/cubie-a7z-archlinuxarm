#!/usr/bin/env python3
"""Rebuild the T5 PowerVR module with generic DRM fdinfo in a private Linux /tmp.

The vendor source/headers remain read-only. No module is installed or loaded.
The returned provenance uses relative source paths, hashes and tool versions.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import tempfile

SOURCE = Path('usr/src/img-bxm-dkms-0.1.0-3')
HEADERS = Path('usr/src/linux-headers-6.6.98-4-aw2511')
ORIGINAL = Path('usr/lib/modules/6.6.98-4-aw2511/updates/dkms/pvrsrvkm.ko.xz')
PATCH = Path(__file__).resolve().parents[1] / 'gpu/kernel/0001-use-generic-drm-fdinfo.patch'
KERNEL_RELEASE = '6.6.98-4-aw2511'
EXPECTED_VERMAGIC = KERNEL_RELEASE + ' SMP mod_unload aarch64'
BUILD_SUBDIR = Path('img-bxm/linux/rogue_km/build/linux/sunxi_linux')
MODULE_SUBPATH = Path('img-bxm/linux/rogue_km/binary_sunxi_linux_nulldrmws_release/target_aarch64/kbuild/pvrsrvkm.ko')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_manifest(root: Path) -> dict:
    """Hash a sorted relative-path manifest, rejecting links outside the tree."""
    root = root.resolve()
    entries = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            target = os.readlink(path)
            if os.path.isabs(target) or not path.resolve().is_relative_to(root):
                raise ValueError('Vendor source/header symlink escapes its input tree')
            entries.append({'path': relative, 'symlink': target})
        elif stat.S_ISREG(mode):
            data = path.read_bytes()
            entries.append({'path': relative, 'size': len(data), 'mode': stat.S_IMODE(mode), 'sha256': sha256(data)})
        elif not stat.S_ISDIR(mode):
            raise ValueError('Vendor source/header tree contains a special file')
    if not entries:
        raise ValueError('Vendor source/header tree is empty')
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    return {'tree_sha256': sha256(encoded), 'entries': len(entries),
            'manifest_format': 'sha256-of-sorted-relative-path-mode-size-content-or-symlink-json-v1'}


def _run(arguments: list[str], *, environment: dict | None = None, cwd: Path | None = None,
         work: Path | None = None) -> str:
    result = subprocess.run(arguments, cwd=cwd, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = '\n'.join(result.stdout.splitlines()[-25:])
        if work is not None:
            tail = tail.replace(str(work), '/build/a7z-gpu').replace(work.as_posix(), '/build/a7z-gpu')
        raise RuntimeError(f'GPU module build step {Path(arguments[0]).name} failed ({result.returncode}):\n{tail}')
    return result.stdout


def _elf_aarch64(data: bytes) -> None:
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise RuntimeError('GPU module output is not a little-endian AArch64 ELF')


def _undefined_symbols(output: str) -> set[str]:
    return {fields[-1] for line in output.splitlines() if len(fields := line.split()) >= 2 and fields[-2] == 'U'}


def build_fixed_module(vendor_root: Path, source_date_epoch: int, jobs: int = 2) -> tuple[bytes, dict]:
    """Return rebuilt ELF bytes and public provenance, never mutating vendor_root."""
    if not isinstance(source_date_epoch, int) or source_date_epoch < 0:
        raise ValueError('source_date_epoch must be a nonnegative integer')
    if not isinstance(jobs, int) or not 1 <= jobs <= 256:
        raise ValueError('jobs must be in 1..256')
    timestamp = datetime.datetime.fromtimestamp(source_date_epoch, datetime.timezone.utc)
    if platform.system() != 'Linux':
        raise RuntimeError('Build the GPU module on Linux (WSL is supported)')
    machine = platform.machine().lower()
    if machine in ('aarch64', 'arm64'):
        prefix = ''
    elif machine in ('x86_64', 'amd64'):
        prefix = 'aarch64-linux-gnu-'
    else:
        raise RuntimeError('GPU builder supports aarch64 or x86_64 Linux hosts')
    commands = ['make', 'patch', 'gcc', 'g++', 'modinfo', *[prefix + name for name in ('gcc', 'ld', 'nm', 'objcopy', 'objdump')]]
    missing = sorted({name for name in commands if shutil.which(name) is None})
    if missing:
        raise RuntimeError('Missing GPU build tools: ' + ', '.join(missing))
    root = Path(vendor_root).resolve()
    source = root / SOURCE
    headers = root / HEADERS
    for path in (source, headers):
        if not path.is_dir() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or external T5 source/header input')
    if not (root / ORIGINAL).is_file() or not (root / ORIGINAL).resolve().is_relative_to(root):
        raise ValueError('Missing or external original T5 module')
    inputs = [dict(path=SOURCE.as_posix(), **tree_manifest(source)),
              dict(path=HEADERS.as_posix(), **tree_manifest(headers))]
    compressed_original = (root / ORIGINAL).read_bytes()
    original_elf = lzma.decompress(compressed_original)
    _elf_aarch64(original_elf)
    patch_bytes = PATCH.read_bytes()
    versions = {name: _run([name, '--version']).splitlines()[0] for name in sorted(set(commands))}
    compiler_header = (headers / 'include/generated/compile.h').read_text()
    compiler = re.search(r'^#define\s+LINUX_COMPILER\s+"([^"]+)"', compiler_header, re.M)
    kernel_compiler = compiler.group(1) if compiler else 'unavailable'
    config = (headers / '.config').read_text()
    modversions = bool(re.search(r'^CONFIG_MODVERSIONS=y$', config, re.M))
    if modversions:
        raise ValueError('Unexpected T5 CONFIG_MODVERSIONS setting; review the new vendor baseline')
    if f'"{KERNEL_RELEASE}"' not in (headers / 'include/generated/utsrelease.h').read_text():
        raise ValueError('T5 kernel header release mismatch')
    with tempfile.TemporaryDirectory(prefix='a7z-gpu-kmod-', dir='/tmp') as temporary:
        work = Path(temporary)
        build_source = work / 'source'
        build_headers = work / 'headers'
        shutil.copytree(source, build_source, symlinks=True)
        shutil.copytree(headers, build_headers, symlinks=True)
        local_patch = work / 'fdinfo.patch'
        local_patch.write_bytes(patch_bytes)
        environment = dict(os.environ, LC_ALL='C', LANG='C', SOURCE_DATE_EPOCH=str(source_date_epoch),
            KBUILD_BUILD_USER='builder', KBUILD_BUILD_HOST='a7z', KBUILD_BUILD_VERSION='1',
            KBUILD_BUILD_TIMESTAMP=timestamp.strftime('%a %b %d %H:%M:%S UTC %Y'))
        _run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', str(local_patch)],
             environment=environment, cwd=build_source, work=work)
        # Debian's target header package contains ARM-host build helpers. Build
        # native-host equivalents from the matching shipped helper sources.
        _run(['gcc', '-O2', '-o', str(build_headers / 'scripts/basic/fixdep'),
              str(build_headers / 'scripts/basic/fixdep.c')], environment=environment, work=work)
        moddir = build_headers / 'scripts/mod'
        _run(['gcc', '-O2', '-I' + str(moddir), '-I' + str(build_headers / 'tools/include'),
              '-o', str(moddir / 'modpost'), *[str(moddir / name) for name in
                  ('modpost.c', 'file2alias.c', 'sumversion.c', 'symsearch.c')]], environment=environment, work=work)
        prefix_flags = f'-ffile-prefix-map={work}=/build/a7z-gpu -fmacro-prefix-map={work}=/build/a7z-gpu'
        _run(['make', f'-j{jobs}', 'BUILD=release', 'ARCH=arm64', 'CROSS_COMPILE=' + prefix,
              'KERNEL_CC=' + prefix + 'gcc', 'KERNEL_LD=' + prefix + 'ld',
              'KERNEL_NM=' + prefix + 'nm', 'KERNEL_OBJCOPY=' + prefix + 'objcopy',
              'KERNELDIR=' + str(build_headers), 'KCFLAGS=' + prefix_flags,
              '-C', str(build_source / BUILD_SUBDIR)], environment=environment, work=work)
        module = build_source / MODULE_SUBPATH
        module_bytes = module.read_bytes()
        _elf_aarch64(module_bytes)
        old_module = work / 'original.ko'
        old_module.write_bytes(original_elf)
        for field in ('name', 'vermagic'):
            actual = _run(['modinfo', '-F', field, str(module)], work=work).strip()
            original = _run(['modinfo', '-F', field, str(old_module)], work=work).strip()
            expected = 'pvrsrvkm' if field == 'name' else EXPECTED_VERMAGIC
            if actual != original or actual != expected:
                raise RuntimeError('Rebuilt module identity/vermagic differs from the original T5 module')
        imports = _undefined_symbols(_run([prefix + 'nm', '-u', str(module)], work=work))
        old_imports = _undefined_symbols(_run([prefix + 'nm', '-u', str(old_module)], work=work))
        exports = {line.split()[1] for line in (headers / 'Module.symvers').read_text().splitlines()}
        if imports - exports:
            raise RuntimeError('Rebuilt module imports symbols missing from T5 Module.symvers')
        if imports - old_imports:
            raise RuntimeError('Rebuilt module introduces imports absent from the original T5 module')
        disassembly = _run([prefix + 'objdump', '-dr', '--disassemble=pvr_show_fdinfo', str(module)], work=work)
        if not re.search(r'R_AARCH64_(?:CALL|JUMP)26\s+drm_show_fdinfo\b', disassembly) or 'PVRDKFTraverse' in disassembly:
            raise RuntimeError('Compiled fdinfo callback does not match the generic DRM fix')
        if str(work).encode() in module_bytes:
            raise RuntimeError('Rebuilt module leaks a temporary build path')
    # Detect accidental writes or a concurrently replaced vendor tree.
    if inputs != [dict(path=SOURCE.as_posix(), **tree_manifest(source)), dict(path=HEADERS.as_posix(), **tree_manifest(headers))]:
        raise RuntimeError('Vendor source/header inputs changed during module build')
    provenance = {
        'schema': 1, 'fix': 'generic-drm-fdinfo', 'source_date_epoch': source_date_epoch,
        'module_sha256': sha256(module_bytes), 'original_module_sha256': sha256(compressed_original),
        'original_elf_sha256': sha256(original_elf), 'original_module_path': ORIGINAL.as_posix(),
        'vermagic': EXPECTED_VERMAGIC, 'inputs': inputs,
        'patch': {'path': 'gpu/kernel/0001-use-generic-drm-fdinfo.patch', 'sha256': sha256(patch_bytes)},
        'toolchain': {'host_machine': machine, 'versions': versions, 'kernel_compiler': kernel_compiler},
        'build': {'target': 'sunxi_linux', 'mode': 'release', 'arch': 'arm64',
                  'native_header_helpers': ['scripts/basic/fixdep', 'scripts/mod/modpost'],
                  'source_path_mapping': '/build/a7z-gpu', 'build_user': 'builder', 'build_host': 'a7z'},
        'validation': {'aarch64_elf': True, 'matching_vermagic': True, 'imports_count': len(imports),
                       'new_imports': [], 'imports_missing_from_headers': [],
                       'removed_imports': sorted(old_imports - imports), 'generic_drm_callback': True,
                       'config_modversions': modversions, 'symbol_crc_validation_available': False,
                       'hardware_tested_by_builder': False},
        'limitation': 'GPU-specific fdinfo statistics are omitted. Rendering and ioctl code are unchanged by the patch; unrelated ioctl lifetime defects are not claimed fixed.',
    }
    return module_bytes, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', type=Path, required=True)
    parser.add_argument('--source-date-epoch', type=int, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must not already exist')
    module, report = build_fixed_module(args.vendor_root, args.source_date_epoch, args.jobs)
    args.output.mkdir(parents=True)
    (args.output / 'pvrsrvkm.ko').write_bytes(module)
    (args.output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'module_sha256': report['module_sha256'], 'vermagic': report['vermagic']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
