"""Safety and reproducibility checks for the optional, isolated VPU package."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import package_vpu as vpu


class PackageBoundaryTests(unittest.TestCase):
    def test_paths_cannot_escape_or_cover_arch_libraries(self):
        for name in ('../usr/lib/libEGL.so', '/usr/lib/libVE.so', 'usr/../etc/environment',
                     'usr\\lib\\bad', 'usr/lib/bad\npath'):
            with self.assertRaises(ValueError):
                vpu.destination_allowed(name)
        for name in ('etc/environment', 'etc/ld.so.conf.d/vpu.conf', 'usr/lib/libVE.so',
                     'usr/lib/gstreamer-1.0/libgstomx.so', 'usr/bin/chromium'):
            self.assertFalse(vpu.destination_allowed(name))
        self.assertTrue(vpu.destination_allowed(vpu.PRIVATE + '/lib/libVE.so'))

    def test_pinned_destinations_are_unique_and_private(self):
        pins = json.loads((vpu.REPO / 'vpu/t5-sources.json').read_text())
        names = [item['destination'] for item in pins['files']]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(vpu.destination_allowed(name) for name in names))
        self.assertFalse(any('chromium' in name for name in names))

    def test_changed_source_file_and_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            info = root / 'var/lib/dpkg/info'
            info.mkdir(parents=True)
            status = []
            packages = {}
            for name, version in vpu.PACKAGES.items():
                status.append(f'Package: {name}\nStatus: install ok installed\nVersion: {version}\n')
                data = b'/usr/lib/payload.so\n'
                (info / (name + '.list')).write_bytes(data)
                packages[name] = {'version': version, 'dpkg_list_sha256': hashlib.sha256(data).hexdigest()}
            (root / 'var/lib/dpkg/status').write_text('\n'.join(status))
            source = root / 'usr/lib/payload.so'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'changed')
            pins = {'schema': 1, 'vendor_release': 'rsdk-t5', 'packages': packages,
                    'files': [{'package': next(iter(vpu.PACKAGES)), 'source': 'usr/lib/payload.so',
                               'destination': vpu.PRIVATE + '/lib/libVE.so',
                               'sha256': hashlib.sha256(b'original').hexdigest()}]}
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                vpu.verify_sources(root, pins)
            (root / 'var/lib/dpkg/status').write_text('\n'.join(status).replace('Version: 1.0.7', 'Version: 9'))
            with self.assertRaisesRegex(ValueError, 'version mismatch'):
                vpu.verify_sources(root, pins)

    @unittest.skipUnless(shutil.which('zstd'), 'Linux zstd required')
    def test_archive_reproducible_and_refuses_symlinks_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / 'stage'
            (stage / 'usr/share/test').mkdir(parents=True)
            (stage / 'usr/share/test/data').write_bytes(b'fixed payload\n')
            hashes = []
            for name in ('one', 'two'):
                out = root / name
                out.mkdir()
                package = vpu.archive(stage, out, 1785826451)
                hashes.append(vpu.helper.sha256(package))
                listing = subprocess.check_output(['tar', '-tf', str(package)], text=True).splitlines()
                self.assertIn('.PKGINFO', listing)
                self.assertIn('.MTREE', listing)
                with self.assertRaises(ValueError):
                    vpu.archive(stage, out, 1785826451)
            self.assertEqual(*hashes)
            (stage / 'escape').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'file type'):
                vpu.archive(stage, root / 'one', 1785826451)

    @unittest.skipUnless(os.name == 'posix', 'POSIX shell required')
    def test_wrapper_keeps_gpu_variables_and_confines_library_selection(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, 'HOME': home, 'XDG_CACHE_HOME': home + '/cache',
                   'LD_LIBRARY_PATH': '/unrelated/libraries', 'QSG_RHI_BACKEND': 'vulkan',
                   'GST_PLUGIN_PATH_1_0': '/unrelated/plugins', 'GST_REGISTRY_1_0': '/unrelated/registry',
                   'VK_DRIVER_FILES': '/existing/vulkan-icd.json'}
            output = subprocess.check_output(['sh', str(vpu.REPO / 'vpu/a7z-vpu-run'), 'env'], env=env, text=True)
            child = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
            self.assertEqual(child['LD_LIBRARY_PATH'], '/' + vpu.PRIVATE + '/lib')
            self.assertEqual(child['GST_PLUGIN_PATH'], '/' + vpu.PRIVATE + '/gstreamer-1.0')
            self.assertEqual(child['GST_PLUGIN_PATH_1_0'], child['GST_PLUGIN_PATH'])
            self.assertEqual(child['GST_REGISTRY_1_0'], child['GST_REGISTRY'])
            self.assertEqual(child['VK_DRIVER_FILES'], env['VK_DRIVER_FILES'])
            self.assertEqual(child['QSG_RHI_BACKEND'], 'vulkan')
            self.assertTrue(child['GST_REGISTRY'].startswith(home + '/cache/a7z-vpu/'))


if __name__ == '__main__':
    unittest.main()
