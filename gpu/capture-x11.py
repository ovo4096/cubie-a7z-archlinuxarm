#!/usr/bin/env python3
"""Read the X11 root window into a PNG without installing screenshot tools.

Example:
  python3 capture-x11.py --display :0 --xauthority /run/lightdm/root/:0 \
      --output /var/tmp/a7z-lightdm.png

Requires only Python's standard library and the installed libX11.so.6. The
display and authority file are always explicit; no fallback to DISPLAY occurs.
The authentication cookie is never printed. No X11 window or setting is changed.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib


class XImage(C.Structure):
    # Public Xlib structure; only the prefix through obdata is inspected. Its
    # trailing function-pointer table remains owned and used by libX11.
    _fields_ = [
        ("width", C.c_int), ("height", C.c_int), ("xoffset", C.c_int),
        ("format", C.c_int), ("data", C.c_void_p), ("byte_order", C.c_int),
        ("bitmap_unit", C.c_int), ("bitmap_bit_order", C.c_int),
        ("bitmap_pad", C.c_int), ("depth", C.c_int),
        ("bytes_per_line", C.c_int), ("bits_per_pixel", C.c_int),
        ("red_mask", C.c_ulong), ("green_mask", C.c_ulong),
        ("blue_mask", C.c_ulong), ("obdata", C.c_void_p),
    ]


class XErrorEvent(C.Structure):
    _fields_ = [
        ("type", C.c_int), ("display", C.c_void_p), ("resourceid", C.c_ulong),
        ("serial", C.c_ulong), ("error_code", C.c_ubyte),
        ("request_code", C.c_ubyte), ("minor_code", C.c_ubyte),
    ]


def bind(library, name, restype, *argtypes):
    function = getattr(library, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(width: int, height: int, rows) -> bytes:
    compressor = zlib.compressobj(level=6)
    parts = []
    count = 0
    for row in rows:
        if len(row) != width * 3:
            raise ValueError("Incorrect RGB row length")
        parts.append(compressor.compress(b"\0" + row))
        count += 1
    if count != height:
        raise ValueError("Incorrect image height")
    parts.append(compressor.flush())
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", b"".join(parts)) + png_chunk(b"IEND", b"")


def mask_info(mask: int) -> tuple[int, int]:
    if mask == 0:
        raise ValueError("Indexed-colour X11 visuals are unsupported; a TrueColor display is required")
    shift = (mask & -mask).bit_length() - 1
    maximum = mask >> shift
    if maximum & (maximum + 1):
        raise ValueError("Non-contiguous X11 colour mask is unsupported")
    return shift, maximum


def rgb_rows(image: XImage, pixel_at=None):
    """Convert XImage pixels according to masks/endianness, respecting stride."""
    width, height, stride = image.width, image.height, image.bytes_per_line
    masks = (image.red_mask, image.green_mask, image.blue_mask)
    channels = [mask_info(mask) for mask in masks]
    if image.byte_order not in (0, 1):
        raise ValueError("Invalid XImage byte order")
    byteorder = "little" if image.byte_order == 0 else "big"
    bpp = image.bits_per_pixel
    if image.format != 2 or bpp not in (8, 16, 24, 32):
        if pixel_at is None:
            raise ValueError(f"Unsupported XImage layout: format={image.format}, bpp={bpp}")
        for y in range(height):
            row = bytearray(width * 3)
            for x in range(width):
                pixel = pixel_at(x, y)
                for channel, ((shift, maximum), mask) in enumerate(zip(channels, masks)):
                    row[x * 3 + channel] = (((pixel & mask) >> shift) * 255 + maximum // 2) // maximum
            yield bytes(row)
        return
    bytes_per_pixel = bpp // 8
    offset = image.xoffset * bytes_per_pixel
    if not image.data or stride < offset + width * bytes_per_pixel or image.xoffset < 0:
        raise ValueError("Invalid XImage data, stride, or offset")
    raw = C.string_at(image.data, stride * height)
    # Typical depth-24/bpp-32 root windows: slice conversion avoids millions of
    # ctypes calls and is fast on the board. RGB565/30-bit use scaled masks.
    fast = all(maximum == 255 and shift % 8 == 0 and shift < bpp for shift, maximum in channels)
    byte_indices = [shift // 8 if byteorder == "little" else bytes_per_pixel - 1 - shift // 8
                    for shift, _ in channels]
    for y in range(height):
        start = y * stride + offset
        source = raw[start:start + width * bytes_per_pixel]
        row = bytearray(width * 3)
        if fast:
            for channel, index in enumerate(byte_indices):
                row[channel::3] = source[index::bytes_per_pixel]
        else:
            for x in range(width):
                pixel = int.from_bytes(source[x * bytes_per_pixel:(x + 1) * bytes_per_pixel], byteorder)
                for channel, ((shift, maximum), mask) in enumerate(zip(channels, masks)):
                    row[x * 3 + channel] = (((pixel & mask) >> shift) * 255 + maximum // 2) // maximum
        yield bytes(row)


def capture(display_name: str, authority: Path, output: Path, max_pixels: int = 32_000_000) -> dict:
    if not display_name:
        raise ValueError("An explicit, nonempty X11 display is required")
    if not authority.is_file():
        raise ValueError("The explicitly supplied XAUTHORITY file does not exist")
    os.environ["XAUTHORITY"] = str(authority.resolve())
    x11 = C.CDLL("libX11.so.6")
    open_display = bind(x11, "XOpenDisplay", C.c_void_p, C.c_char_p)
    close_display = bind(x11, "XCloseDisplay", C.c_int, C.c_void_p)
    default_root = bind(x11, "XDefaultRootWindow", C.c_ulong, C.c_void_p)
    geometry = bind(x11, "XGetGeometry", C.c_int, C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong),
                    C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_uint),
                    C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint))
    get_image = bind(x11, "XGetImage", C.POINTER(XImage), C.c_void_p, C.c_ulong,
                     C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int)
    destroy_image = bind(x11, "XDestroyImage", C.c_int, C.POINTER(XImage))
    get_pixel = bind(x11, "XGetPixel", C.c_ulong, C.POINTER(XImage), C.c_int, C.c_int)
    sync = bind(x11, "XSync", C.c_int, C.c_void_p, C.c_int)
    error_callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(XErrorEvent))
    errors = []

    @error_callback_type
    def error_handler(_display, event):
        errors.append({"error_code": event.contents.error_code, "request_code": event.contents.request_code,
                       "minor_code": event.contents.minor_code})
        return 0

    set_handler = bind(x11, "XSetErrorHandler", C.c_void_p, C.c_void_p)
    old_handler = set_handler(C.cast(error_handler, C.c_void_p))
    display = None
    image = None
    try:
        display = open_display(display_name.encode())
        if not display:
            raise RuntimeError("Cannot open the explicitly requested X display; check its availability and XAUTHORITY access")
        root = default_root(display)
        root_return, x, y = C.c_ulong(), C.c_int(), C.c_int()
        width, height, border, depth = C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
        ok = geometry(display, root, C.byref(root_return), C.byref(x), C.byref(y), C.byref(width),
                      C.byref(height), C.byref(border), C.byref(depth))
        if not ok or errors:
            raise RuntimeError(f"XGetGeometry failed: {errors}")
        if not width.value or not height.value or width.value * height.value > max_pixels:
            raise ValueError(f"Display dimensions exceed the allowed capture size: {width.value}x{height.value}")
        all_planes = C.c_ulong(-1).value
        image = get_image(display, root, 0, 0, width.value, height.value, all_planes, 2)
        sync(display, 0)
        if not image or errors:
            raise RuntimeError(f"XGetImage failed: {errors}")
        if image.contents.width != width.value or image.contents.height != height.value:
            raise RuntimeError("Display dimensions changed during capture")
        data = png_bytes(width.value, height.value, rgb_rows(image.contents, lambda px, py: get_pixel(image, px, py)))
        output = output.absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".x11-capture-", suffix=".png", dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"status": "captured", "display": display_name, "depth": depth.value,
                "width": width.value, "height": height.value, "dimensions": f"{width.value}x{height.value}",
                "bits_per_pixel": image.contents.bits_per_pixel, "output": str(output), "bytes": len(data)}
    finally:
        if image:
            destroy_image(image)
        if display:
            close_display(display)
        set_handler(old_handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", required=True, help="explicit X display, e.g. :0")
    parser.add_argument("--xauthority", required=True, type=Path, help="explicit X authentication file; never printed")
    parser.add_argument("--output", required=True, type=Path, help="PNG destination")
    parser.add_argument("--max-pixels", type=int, default=32_000_000)
    args = parser.parse_args()
    if args.max_pixels <= 0:
        parser.error("--max-pixels must be positive")
    try:
        result = capture(args.display, args.xauthority, args.output, args.max_pixels)
    except (OSError, RuntimeError, ValueError, AttributeError) as exc:
        print(json.dumps({"status": "failed", "display": args.display, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
