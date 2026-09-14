import ctypes as C
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SCRIPT = Path(__file__).with_name("capture-x11.py")
SPEC = importlib.util.spec_from_file_location("capture_x11", SCRIPT)
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


class XImageConversionTests(unittest.TestCase):
    def make_image(self, raw, **values):
        storage = C.create_string_buffer(raw)
        image = CAPTURE.XImage(format=2, data=C.cast(storage, C.c_void_p), **values)
        return image, storage

    def test_little_endian_pixels_and_padded_rows(self):
        image, storage = self.make_image(
            bytes.fromhex("0000ff00 00ff0000 aabbccdd ff000000 ffffff00 aabbccdd"),
            width=2, height=2, depth=24, bits_per_pixel=32, byte_order=0,
            bytes_per_line=12, red_mask=0xFF0000, green_mask=0xFF00, blue_mask=0xFF,
        )
        self.assertEqual(list(CAPTURE.rgb_rows(image)), [bytes.fromhex("ff0000 00ff00"), bytes.fromhex("0000ff ffffff")])

    def test_rgb565_scaling_and_big_endian(self):
        image, storage = self.make_image(bytes.fromhex("f800 07e0 001f"), width=3, height=1,
                                         depth=16, bits_per_pixel=16, byte_order=1,
                                         bytes_per_line=6, red_mask=0xF800, green_mask=0x7E0, blue_mask=0x1F)
        self.assertEqual(list(CAPTURE.rgb_rows(image)), [bytes.fromhex("ff0000 00ff00 0000ff")])

    def test_png_has_correct_dimensions_crc_and_rgb_scanline(self):
        png = CAPTURE.png_bytes(2, 1, [bytes.fromhex("ff0000 00ff00")])
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        offset, chunks = 8, {}
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            kind = png[offset + 4:offset + 8]
            data = png[offset + 8:offset + 8 + length]
            checksum = struct.unpack(">I", png[offset + 8 + length:offset + 12 + length])[0]
            self.assertEqual(checksum, zlib.crc32(kind + data) & 0xFFFFFFFF)
            chunks[kind] = data
            offset += 12 + length
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[b"IHDR"]), (2, 1, 8, 2, 0, 0, 0))
        self.assertEqual(zlib.decompress(chunks[b"IDAT"]), bytes.fromhex("00 ff0000 00ff00"))


class NoDisplayTests(unittest.TestCase):
    def test_missing_explicit_display_never_falls_back_to_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist.png"
            result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                                    env={key: value for key, value in os.environ.items() if key not in ("DISPLAY", "XAUTHORITY")},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("--display", result.stderr)
            self.assertFalse(output.exists())

    def test_unavailable_local_display_creates_no_artifact(self):
        if Path("/tmp/.X11-unix/X9876").exists():
            self.skipTest("The negative-control socket unexpectedly exists")
        try:
            C.CDLL("libX11.so.6")
        except OSError:
            self.skipTest("Host libX11 is absent; no dependency installation requested")
        with tempfile.TemporaryDirectory() as directory:
            authority, output = Path(directory) / "empty.Xauthority", Path(directory) / "must-not-exist.png"
            authority.write_bytes(b"")
            env = {key: value for key, value in os.environ.items() if key not in ("DISPLAY", "XAUTHORITY")}
            result = subprocess.run([sys.executable, str(SCRIPT), "--display", ":9876", "--xauthority", str(authority),
                                     "--output", str(output)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Cannot open", result.stdout)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
