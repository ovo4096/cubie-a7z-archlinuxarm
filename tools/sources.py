#!/usr/bin/env python3
"""Fetch fixed build inputs and reject any changed upstream artifact."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request


def verify(path, item):
    if not path.is_file():
        raise FileNotFoundError(path)
    if "size" in item and path.stat().st_size != item["size"]:
        raise ValueError(f"Wrong length: {path}")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != item["sha256"]:
        raise ValueError(f"SHA256 mismatch: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "verify"])
    parser.add_argument("--lock", type=Path, default=Path(__file__).resolve().parents[1] / "config/sources.lock.json")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--role", action="append", help="Only process this artifact role (repeatable)")
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    args.cache.mkdir(parents=True, exist_ok=True)
    items = [x for x in lock["artifacts"] if not args.role or x["role"] in args.role]
    if not items:
        parser.error("No artifacts match the requested roles")
    for item in items:
        if Path(item["name"]).name != item["name"]:
            raise ValueError("Artifact name must be a filename")
        target = args.cache / item["name"]
        if args.action == "fetch" and not target.exists():
            partial = target.with_name(target.name + ".part")
            request = urllib.request.Request(item["url"], headers={"User-Agent": "a7z-archlinuxarm-builder/0.1"})
            print(f"Downloading {item['name']}", flush=True)
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    out.write(chunk)
            verify(partial, item)
            partial.replace(target)
        verify(target, item)
        print(f"Verified {item['name']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
