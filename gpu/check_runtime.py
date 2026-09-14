#!/usr/bin/env python3
"""Resolve userspace ELF imports eagerly; this does not initialize the GPU."""
import argparse
import ctypes
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--private-dir", type=Path, default=Path("/usr/lib/radxa-a7z-gpu"))
args = parser.parse_args()
report = {"validation": "RTLD_NOW only; no GPU rendering", "libraries": [], "icd_api_version": None}
handles = []
for path in sorted(list((args.private_dir / "lib").glob("*.so*")) + list((args.private_dir / "dri").glob("*.so*"))):
    if path.is_symlink():
        continue
    try:
        handle = ctypes.CDLL(str(path), mode=os.RTLD_NOW | os.RTLD_LOCAL)
        handles.append(handle)
        report["libraries"].append({"file": str(path.relative_to(args.private_dir)), "status": "load-pass"})
        if path.name.startswith("libVK_IMG.so"):
            lookup = handle.vk_icdGetInstanceProcAddr
            lookup.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lookup.restype = ctypes.c_void_p
            address = lookup(None, b"vkEnumerateInstanceVersion")
            if address:
                query = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(ctypes.c_uint32))(address)
                version = ctypes.c_uint32()
                code = query(ctypes.byref(version))
                if code == 0:
                    report["icd_api_version"] = f"{(version.value >> 22) & 127}.{(version.value >> 12) & 1023}.{version.value & 4095}"
    except (OSError, AttributeError) as exc:
        report["libraries"].append({"file": str(path.relative_to(args.private_dir)), "status": "failed", "error": str(exc)})
report["status"] = "load-pass" if report["libraries"] and all(item["status"] == "load-pass" for item in report["libraries"]) else "failed"
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["status"] == "load-pass" else 1)
