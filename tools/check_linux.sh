#!/usr/bin/env bash
# Builds the extension for Linux and runs the whole suite there.
#
# Not "some Linux": the image this package is installed into is python:3.12.11-slim-bullseye,
# and bullseye is glibc 2.31. An extension built on bookworm (2.36) does not load there at
# all — `GLIBC_2.34 not found`, at import time, having compiled cleanly. Hence the bullseye
# builder. For wheels that travel further, the answer is manylinux.
#
#   ./tools/check_linux.sh                 # the host's own architecture
#   ./tools/check_linux.sh linux/amd64     # production's; cross-compiled, because rustc
#                                          # segfaults under qemu while its output runs fine
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
platform="${1:-}"
host="linux/$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/; s/x86_64/amd64/')"
target="${platform:-$host}"

build_flags=""
copy_from="/tmp/target/release"
if [ "$target" != "$host" ]; then
  # Cross-compile: rustc segfaults under emulation, but a cross-linker installs happily.
  build_flags="--target x86_64-unknown-linux-gnu"
  copy_from="/tmp/target/x86_64-unknown-linux-gnu/release"
fi

echo "1/2 building the extension (bullseye, target $target)"
docker run --rm --platform "$host" -v "$root":/w -w /w \
  -e PYO3_NO_PYTHON=1 -e CARGO_TARGET_DIR=/tmp/target \
  -e CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=x86_64-linux-gnu-gcc \
  rust:1-slim-bullseye sh -c "
    set -e
    if [ -n '$build_flags' ]; then
      apt-get -qq update >/dev/null && apt-get -qq install -y gcc-x86-64-linux-gnu >/dev/null 2>&1
      rustup target add x86_64-unknown-linux-gnu >/dev/null 2>&1
    fi
    cargo build --release $build_flags --manifest-path rust/Cargo.toml >/dev/null 2>&1
    cp $copy_from/lib_native.so /w/.linux_native.so"

echo "2/2 running the suite in the deployment image"
docker run --rm --platform "$target" -v "$root":/w python:3.12.11-slim-bullseye sh -c '
  set -e
  mkdir -p /build && cp -r /w/src /w/tests /w/pyproject.toml /build/
  cp /w/.linux_native.so /build/src/lz_string/_native.abi3.so
  cd /build && pip -q install pytest >/dev/null 2>&1
  python -m pytest'

rm -f "$root/.linux_native.so"
