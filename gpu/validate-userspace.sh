#!/usr/bin/env bash
# Host-side, read-only Arch rootfs validation. GPU device access is not attempted.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo "Usage: $0 ARCH_ROOTFS GPU_PACKAGE_DIRECTORY REPORT_DIRECTORY" >&2
    exit 2
fi
target=$(realpath "$1")
packages=$(realpath "$2")
mkdir -p "$3"
output=$(realpath "$3")
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
qemu=$(command -v qemu-aarch64-static)
[[ -f "$target/usr/lib/libc.so.6" && -x "$target/usr/bin/python" ]] || {
    echo 'Target Arch rootfs needs glibc and python.' >&2
    exit 2
}
work=$(mktemp -d "$output/gpu-runtime.XXXXXX")
for component in userspace compat xorg; do
    archives=("$packages"/radxa-a7z-gpu-"$component"-*.pkg.tar.zst)
    [[ ${#archives[@]} == 1 && -f ${archives[0]} ]] || {
        echo "Expected exactly one $component package in $packages" >&2
        exit 2
    }
    tar -xf "${archives[0]}" -C "$work"
done
private="$work/usr/lib/radxa-a7z-gpu"
libraries="$private/lib:$private/compat:$target/usr/lib"
link_status=0
env PYTHONHOME="$target/usr" PYTHONDONTWRITEBYTECODE=1 LD_LIBRARY_PATH="$libraries" \
    "$qemu" -L "$target" "$target/usr/bin/python" \
    "$script_dir/check_runtime.py" --private-dir "$private" \
    > "$output/gpu-arch-link-check.json" 2> "$output/gpu-arch-link-check.stderr" || link_status=$?
xorg_status=0
env LD_LIBRARY_PATH="$libraries" "$qemu" -L "$target" "$private/xorg/Xorg" -version \
    > "$output/gpu-arch-xorg-version.txt" 2>&1 || xorg_status=$?
printf 'RTLD_NOW exit: %s\nXorg -version exit: %s\nRetained private payload: %s\n' \
    "$link_status" "$xorg_status" "$work" > "$output/gpu-arch-validation.txt"
cat "$output/gpu-arch-validation.txt"
[[ $link_status == 0 && $xorg_status == 0 ]]
