import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gpu_kmod_builder', ROOT / 'tools/build_gpu_kmod.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class GpuKmodBuilderTests(unittest.TestCase):
    def test_tree_hash_ignores_parent_path_but_detects_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('one', 'two'):
                (root / name / 'nested').mkdir(parents=True)
                (root / name / 'nested/input.c').write_bytes(b'input\n')
            left = builder.tree_manifest(root / 'one')
            self.assertEqual(left, builder.tree_manifest(root / 'two'))
            self.assertNotIn(directory, json.dumps(left))
            (root / 'two/nested/input.c').write_bytes(b'changed\n')
            self.assertNotEqual(left, builder.tree_manifest(root / 'two'))

    def test_tree_rejects_external_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tree').mkdir()
            (root / 'outside').write_bytes(b'private')
            try:
                (root / 'tree/link').symlink_to('../outside')
            except (OSError, NotImplementedError):
                self.skipTest('Symlink creation unavailable on host')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                builder.tree_manifest(root / 'tree')

    def test_empty_input_tree_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'empty'):
                builder.tree_manifest(Path(directory))

    def test_architecture_validation(self):
        data = bytearray(64)
        data[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', data, 18, 183)
        builder._elf_aarch64(bytes(data))
        struct.pack_into('<H', data, 18, 62)
        with self.assertRaisesRegex(RuntimeError, 'AArch64'):
            builder._elf_aarch64(bytes(data))
        with self.assertRaises(RuntimeError):
            builder._elf_aarch64(b'not a module')

    def test_invalid_build_parameters_fail_before_tools(self):
        with patch.object(builder.shutil, 'which') as which:
            for epoch, jobs in ((-1, 2), (0, 0), (0, 257)):
                with self.assertRaises(ValueError):
                    builder.build_fixed_module(Path('unused'), epoch, jobs)
            which.assert_not_called()

    def test_missing_tool_does_not_copy_inputs(self):
        with patch.object(builder.platform, 'system', return_value='Linux'), \
                patch.object(builder.platform, 'machine', return_value='x86_64'), \
                patch.object(builder.shutil, 'which', return_value=None), \
                patch.object(builder.shutil, 'copytree') as copy:
            with self.assertRaisesRegex(RuntimeError, 'Missing GPU build tools'):
                builder.build_fixed_module(Path('unused'), 1)
            copy.assert_not_called()

    def test_symbol_parser_does_not_treat_defined_or_weak_as_required_imports(self):
        self.assertEqual(builder._undefined_symbols('                 U drm_show_fdinfo\n00001 T local\n                 w optional\n'), {'drm_show_fdinfo'})

    def test_failure_output_scrubs_temporary_path(self):
        result = type('Result', (), {'returncode': 2, 'stdout': 'error in /tmp/private-hostname/src.c\n'})()
        with patch.object(builder.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                builder._run(['make'], work=Path('/tmp/private-hostname'))
            self.assertNotIn('private-hostname', str(caught.exception))
            self.assertIn('/build/a7z-gpu/src.c', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
