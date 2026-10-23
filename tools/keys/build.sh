#!/bin/sh
set -eu
TOP=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?usage: build.sh REGISTERED_INPUTS/tools/keys}
sh "$TOP/tools/build-static-helper.sh" "$TOP/tools/keys/mu300-keys.c" "$OUT/mu300-keys"
python3 "$TOP/tools/atd-io/artifact.py" stamp "$OUT/mu300-keys" "$TOP/tools/keys/mu300-keys.c"
