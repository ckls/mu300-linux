#!/bin/sh
# Run through tools/build-release.py run; OUT is the registered inputs/tools/atd-io.
set -eu
TOP=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?usage: build.sh REGISTERED_INPUTS/tools/atd-io}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
sh "$TOP/tools/build-static-helper.sh" "$TOP/tools/atd-io/mu300-atd-io.c" "$OUT/mu300-atd-io"
python3 "$TOP/tools/atd-io/artifact.py" stamp "$OUT/mu300-atd-io"
