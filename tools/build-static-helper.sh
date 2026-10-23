#!/bin/sh
# Shared release-mode ARM64 helper build. Invoke through tools/build-release.py.
set -eu
SOURCE=${1:?source C file required}
OUTPUT=${2:?output binary required}
[ -s "$SOURCE" ] || { echo "missing helper source: $SOURCE" >&2; exit 1; }
SOURCE_DIR=$(cd "$(dirname "$SOURCE")" && pwd)
mkdir -p "$(dirname "$OUTPUT")"
OUTPUT_DIR=$(cd "$(dirname "$OUTPUT")" && pwd)
SOURCE_NAME=$(basename "$SOURCE")
OUTPUT_NAME=$(basename "$OUTPUT")
if [ "$(uname -m)" = aarch64 ]; then CC=${CC:-gcc}; else CC=${CC:-aarch64-linux-gnu-gcc}; fi
command -v "$CC" >/dev/null 2>&1 || { echo "Required ARM64 compiler not found: $CC" >&2; exit 1; }
"$CC" -O2 -Wall -Wextra -Werror -static -o "$OUTPUT_DIR/$OUTPUT_NAME" "$SOURCE_DIR/$SOURCE_NAME"
