#!/usr/bin/env python3
"""Run through a7z-gpu-run; render one GLES pixel and enumerate Vulkan devices."""
import argparse
import ctypes as C
import glob
import json
import os
from pathlib import Path
import sys


def function(lib, name, result, *arguments):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = arguments
    return fn


def egl_probe(device=None):
    egl = C.CDLL("libEGL.so.1", mode=os.RTLD_NOW)
    getproc = function(egl, "eglGetProcAddress", C.c_void_p, C.c_char_p)
    getdisplay = function(egl, "eglGetDisplay", C.c_void_p, C.c_void_p)
    initialize = function(egl, "eglInitialize", C.c_uint, C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int))
    terminate = function(egl, "eglTerminate", C.c_uint, C.c_void_p)
    query = function(egl, "eglQueryString", C.c_char_p, C.c_void_p, C.c_int)
    geterror = function(egl, "eglGetError", C.c_uint)
    platform_ptr = getproc(b"eglGetPlatformDisplayEXT")
    platform = C.CFUNCTYPE(C.c_void_p, C.c_uint, C.c_void_p, C.POINTER(C.c_int))(platform_ptr) if platform_ptr else None
    attempts, gbm, gbm_device, descriptor = [], None, None, None
    display = None
    major, minor = C.c_int(), C.c_int()
    # Prefer surfaceless; some BSP Mesa builds only support a GBM display.
    if platform and not device:
        candidate = platform(0x31DD, None, None)  # EGL_PLATFORM_SURFACELESS_MESA
        if candidate and initialize(candidate, C.byref(major), C.byref(minor)):
            display = candidate
        else:
            attempts.append({"platform": "surfaceless", "error": hex(geterror())})
    if not display:
        gbm = C.CDLL("libgbm.so.1", mode=os.RTLD_NOW)
        create = function(gbm, "gbm_create_device", C.c_void_p, C.c_int)
        destroy = function(gbm, "gbm_device_destroy", None, C.c_void_p)
        devices = [device] if device else sorted(glob.glob("/dev/dri/renderD*")) + sorted(glob.glob("/dev/dri/card*"))
        for path in devices:
            try:
                fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            except OSError as exc:
                attempts.append({"device": path, "error": str(exc)})
                continue
            native = create(fd)
            candidate = platform(0x31D7, native, None) if platform and native else getdisplay(native) if native else None
            if candidate and initialize(candidate, C.byref(major), C.byref(minor)):
                display, gbm_device, descriptor = candidate, native, fd
                attempts.append({"platform": "gbm", "device": path, "initialized": True})
                break
            attempts.append({"platform": "gbm", "device": path, "error": hex(geterror())})
            if native:
                destroy(native)
            os.close(fd)
    if not display:
        return {"status": "failed", "step": "eglInitialize", "attempts": attempts}
    bind = function(egl, "eglBindAPI", C.c_uint, C.c_uint)
    choose = function(egl, "eglChooseConfig", C.c_uint, C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_void_p), C.c_int, C.POINTER(C.c_int))
    create_context = function(egl, "eglCreateContext", C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int))
    create_surface = function(egl, "eglCreatePbufferSurface", C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int))
    makecurrent = function(egl, "eglMakeCurrent", C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p)
    context = surface = None
    try:
        bind(0x30A0)  # EGL_OPENGL_ES_API
        attrs = (C.c_int * 13)(0x3033, 1, 0x3040, 4, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038)
        config, count = C.c_void_p(), C.c_int()
        if not choose(display, attrs, C.byref(config), 1, C.byref(count)) or not count.value:
            return {"status": "failed", "step": "eglChooseConfig-pbuffer", "error": hex(geterror()), "attempts": attempts}
        context = create_context(display, config, None, (C.c_int * 3)(0x3098, 2, 0x3038))
        surface = create_surface(display, config, (C.c_int * 5)(0x3057, 1, 0x3056, 1, 0x3038))
        if not context or not surface or not makecurrent(display, surface, surface, context):
            return {"status": "failed", "step": "eglMakeCurrent", "error": hex(geterror()), "attempts": attempts}
        gl = C.CDLL("libGLESv2.so.2", mode=os.RTLD_NOW)
        string = function(gl, "glGetString", C.c_char_p, C.c_uint)
        clearcolor = function(gl, "glClearColor", None, C.c_float, C.c_float, C.c_float, C.c_float)
        clear = function(gl, "glClear", None, C.c_uint)
        read = function(gl, "glReadPixels", None, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_void_p)
        glerror = function(gl, "glGetError", C.c_uint)
        renderer = (string(0x1F01) or b"").decode(errors="replace")
        vendor = (string(0x1F00) or b"").decode(errors="replace")
        clearcolor(1.0, 0.0, 0.0, 1.0)
        clear(0x4000)
        pixels = (C.c_ubyte * 4)()
        read(0, 0, 1, 1, 0x1908, 0x1401, pixels)
        error = glerror()
        hardware = any(x in (renderer + vendor).lower() for x in ("powervr", "imagination", "bxm", "rogue"))
        hardware = hardware and not any(x in renderer.lower() for x in ("llvmpipe", "softpipe", "swrast", "lavapipe"))
        pixel_ok = list(pixels) == [255, 0, 0, 255] and error == 0
        return {"status": "hardware-render-pass" if hardware and pixel_ok else "failed", "renderer": renderer,
                "vendor": vendor, "egl_vendor": (query(display, 0x3053) or b"").decode(),
                "egl_version": f"{major.value}.{minor.value}", "pixel_rgba": list(pixels),
                "gl_error": hex(error), "attempts": attempts}
    finally:
        makecurrent(display, None, None, None)
        if surface:
            function(egl, "eglDestroySurface", C.c_uint, C.c_void_p, C.c_void_p)(display, surface)
        if context:
            function(egl, "eglDestroyContext", C.c_uint, C.c_void_p, C.c_void_p)(display, context)
        terminate(display)
        if gbm_device:
            destroy(gbm_device)
        if descriptor is not None:
            os.close(descriptor)


def vulkan_probe():
    class CreateInfo(C.Structure):
        _fields_ = [("sType", C.c_uint32), ("pNext", C.c_void_p), ("flags", C.c_uint32),
                    ("pApplicationInfo", C.c_void_p), ("enabledLayerCount", C.c_uint32),
                    ("ppEnabledLayerNames", C.c_void_p), ("enabledExtensionCount", C.c_uint32),
                    ("ppEnabledExtensionNames", C.c_void_p)]
    vk = C.CDLL("libvulkan.so.1", mode=os.RTLD_NOW)
    create = function(vk, "vkCreateInstance", C.c_int32, C.POINTER(CreateInfo), C.c_void_p, C.POINTER(C.c_void_p))
    enumerate_devices = function(vk, "vkEnumeratePhysicalDevices", C.c_int32, C.c_void_p, C.POINTER(C.c_uint32), C.c_void_p)
    props = function(vk, "vkGetPhysicalDeviceProperties", None, C.c_void_p, C.c_void_p)
    destroy = function(vk, "vkDestroyInstance", None, C.c_void_p, C.c_void_p)
    instance = C.c_void_p()
    code = create(C.byref(CreateInfo(sType=1)), None, C.byref(instance))
    if code:
        return {"status": "failed", "step": "vkCreateInstance", "vk_result": code}
    try:
        count = C.c_uint32()
        code = enumerate_devices(instance, C.byref(count), None)
        if code or not count.value:
            return {"status": "failed", "step": "vkEnumeratePhysicalDevices", "vk_result": code, "count": count.value}
        handles = (C.c_void_p * count.value)()
        code = enumerate_devices(instance, C.byref(count), handles)
        devices = []
        for handle in handles[:count.value]:
            # VkPhysicalDeviceProperties starts with five uint32s + char[256].
            # An aligned oversized buffer safely holds the remaining limits.
            storage = (C.c_uint64 * 1024)()
            props(handle, storage)
            words = C.cast(storage, C.POINTER(C.c_uint32))
            name = C.string_at(C.addressof(storage) + 20, 256).split(b"\0")[0].decode(errors="replace")
            devices.append({"name": name, "vendor_id": hex(words[2]), "device_type": words[4],
                            "hardware": words[4] in (1, 2) and words[2] == 0x1010})
        return {"status": "hardware-enumeration-pass" if not code and any(d["hardware"] for d in devices) else "failed",
                "vk_result": code, "devices": devices, "limits": "Enumeration only; no Vulkan draw or compute submitted."}
    finally:
        destroy(instance, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", choices=("egl", "vulkan", "all"), default="all")
    parser.add_argument("--device", help="force this GBM DRM node, skipping surfaceless; default tries available render/card nodes")
    parser.add_argument("--private-dir", type=Path, default=Path("/usr/lib/radxa-a7z-gpu"), help="private payload location for isolated ABI validation")
    args = parser.parse_args()
    try:
        icd = json.loads(Path(os.environ["VK_DRIVER_FILES"]).read_text())
        if Path(icd["ICD"]["library_path"]).resolve() != (args.private_dir / "lib/libVK_IMG.so.1").resolve():
            raise ValueError("ICD points outside the selected private payload")
    except (KeyError, OSError, ValueError) as exc:
        parser.error(f"run through a7z-gpu-run or provide the isolated payload ICD: {exc}")
    output = {}
    for name, probe in (("egl", lambda: egl_probe(args.device)), ("vulkan", vulkan_probe)):
        if args.api in ("all", name):
            try:
                output[name] = probe()
            except (OSError, AttributeError, ValueError) as exc:
                output[name] = {"status": "failed", "error": str(exc)}
    print(json.dumps(output, indent=2))
    return 0 if output and all(x["status"].startswith("hardware-") for x in output.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
