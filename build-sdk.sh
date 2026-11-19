#!/usr/bin/env bash
# Build Mono-101 with the MPC Plugin SDK: native test build + arm32 + arm64, into build/sd88me - VST - Mono-101/.
#   ./build-sdk.sh          build
#   ./build-sdk.sh test     build, check params.lock, run the SDK's host simulator test
#   ./build-sdk.sh beta     a "Mono-101 Beta" (uid M10B) build that installs next to the release
# MPC_SDK: the SDK checkout (default: mpc-vst-plugins' vendored copy).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
SDK="${MPC_SDK:-$HOME/mpc-vst-plugins/vendor/mpc-plugin-builder-sdk}"
[ -f "$SDK/tools/build.py" ] || { echo "need the SDK (MPC_SDK)" >&2; exit 1; }
# params.lock: the parameter ids in OneX1Plugin.cpp's order, frozen (append only).
python3 - "$here" <<'PY'
import re, sys
src = open(sys.argv[1] + "/src/OneX1Plugin.cpp").read()
ids = re.findall(r'(?:slider|Param)\("([a-z0-9_]+)"', src)
# the naming keyboard's keys are made in a loop from kKbChars: kb_<char> (kb_dash), then the five named keys
chars = re.search(r'kKbChars\[\] = "([^"]+)"', src)
if chars and "kb_open" in ids:
    at = ids.index("kb_open") + 1
    ids[at:at] = [("kb_dash" if c == "-" else "kb_" + c.lower()) for c in chars.group(1)] + \
                 ["kb_space", "kb_bksp", "kb_shift", "kb_cancel", "kb_save"]
lock = open(sys.argv[1] + "/params.lock").read().split()
if ids[:len(lock)] != lock:
    sys.exit("params.lock: the parameter order changed (append only)\n  lock: %s\n  src:  %s" % (lock, ids))
if len(ids) > len(lock):
    sys.exit("params.lock: new parameters %s: append them to params.lock" % ids[len(lock):])
PY
python3 "$here/tools/gen_presets.py"
python3 "$here/tools/make_tui.py"
if [ "${1:-}" = beta ]; then
  stage="$here/build/beta-project"; rm -rf "$stage"; mkdir -p "$stage"
  ln -s "$here/src" "$stage/src"; [ -d "$here/skins" ] && ln -s "$here/skins" "$stage/skins"
  python3 - "$here/plugin.json" "$stage/plugin.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m.update(name="Mono-101 Beta", uid="M10B", file32="VST/mono101beta-arm32.so", file64="VST/mono101beta-arm64.so")
json.dump(m, open(sys.argv[2], "w"), indent=2)
PY
  python3 "$SDK/tools/build.py" "$stage" --no-ui --define 'ONEX1_NAME="Mono-101 Beta"' --define "ONEX1_UID='M','1','0','B'"
  exit
fi
python3 "$SDK/tools/build.py" "$here" --no-ui
if [ "${1:-}" = test ]; then
  "$SDK/.sdk-tools/host_sim" "$here/build/native/mono-101.so" test --notes 48,55,60 --wav "$here/build/test.wav"
fi
