#!/usr/bin/env bash
# Builds the extension in place, next to the Python module.
#
# A script rather than maturin because working in the checkout does not need a wheel, only
# a .so under src/lz_string/ for the tests to import. `pip install .` uses maturin and does
# the same thing plus the wheel metadata.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/rust"
cargo build --release
case "$(uname -s)" in
  Darwin) built="target/release/lib_native.dylib" ;;
  *)      built="target/release/lib_native.so" ;;
esac
cp "$built" "$root/src/lz_string/_native.so"
echo "built: src/lz_string/_native.so"
