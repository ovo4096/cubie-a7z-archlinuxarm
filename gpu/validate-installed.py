#!/usr/bin/env python3
"""Read-only installed-stack GPU check for board.py --python after a T5 boot.

Uses the package's opt-in wrapper, captures actual mappings in the same process,
does not start Xorg, load modules, write files or change services.
"""
import glob
import json
import os
from pathlib import Path
import subprocess

plans = [("link-check", "/usr/bin/a7z-gpu-link-check", []),
         ("egl-auto", "/usr/bin/a7z-gpu-probe", ["--api", "egl"]),
         ("vulkan", "/usr/bin/a7z-gpu-probe", ["--api", "vulkan"])]
for device in sorted(glob.glob("/dev/dri/renderD*")):
    plans.append(("egl-" + Path(device).name, "/usr/bin/a7z-gpu-probe", ["--api", "egl", "--device", device]))
report = {"kernel": os.uname().release, "euid": os.geteuid(), "tests": []}
for name, program, arguments in plans:
    code = "\n".join([
        "import contextlib, io, json, pathlib, runpy, sys",
        "sys.argv = " + repr([program, *arguments]),
        "stream = io.StringIO(); status = 0",
        "try:",
        "    with contextlib.redirect_stdout(stream):",
        "        runpy.run_path(" + repr(program) + ", run_name='__main__')",
        "except SystemExit as exc:",
        "    status = exc.code or 0",
        "paths = sorted(set(line.split()[-1] for line in pathlib.Path('/proc/self/maps').read_text().splitlines() if '/' in line))",
        "try: result = json.loads(stream.getvalue())",
        "except ValueError: result = stream.getvalue()",
        "print(json.dumps({'result': result, 'loaded_paths': paths, 'legacy_usr_local_loaded': [p for p in paths if p.startswith('/usr/local/')]}))",
        "raise SystemExit(status)",
    ])
    try:
        result = subprocess.run(["/usr/bin/a7z-gpu-run", "python3", "-c", code],
                                capture_output=True, text=True, timeout=20)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = result.stdout
        report["tests"].append({"name": name, "exit_code": result.returncode, "data": data, "stderr": result.stderr})
    except (OSError, subprocess.TimeoutExpired) as exc:
        report["tests"].append({"name": name, "exit_code": 124, "error": str(exc)})
report["status"] = "pass" if all(test["exit_code"] == 0 and isinstance(test.get("data"), dict)
                                 and not test["data"].get("legacy_usr_local_loaded") for test in report["tests"]) else "failed"
report["limits"] = "EGL verifies one GLES2 pixel; Vulkan only enumerates devices. No display-server or stability test."
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["status"] == "pass" else 1)
