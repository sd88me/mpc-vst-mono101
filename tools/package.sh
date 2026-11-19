#!/usr/bin/env bash
# The release zips (Gen2 / 64-bit MPCs: the Gen1 build is made but not measured or offered yet). Builds the release identity
# ("Mono-101", uid M101), runs the offline tests, then packs:
#   dist/Mono-101-<ver>-mpc-aarch64.zip   Live III and other 64-bit MPCs: install.sh, the catalog / Plugin Manager zip
#   dist/Mono-101-<ver>-mpc-sdk.zip       the same folder for copying into "VST2 Plugins" by hand (MPC OS 3.10 or later)
#   dist/Mono-101-<ver>-SHA256SUMS.txt
# User presets (mono101-presets.txt next to the .so) are kept on upgrade.
# MPC_VST: an mpc-vst-plugins checkout with tools/release.py, tools/sdk_zip.py and tools/catalog_check.py.
set -euo pipefail
cd "$(dirname "$0")/.."
MPC_VST="${MPC_VST:-$HOME/mpc-vst-plugins-postlaunch}"
for t in release.py sdk_zip.py catalog_check.py; do
  [ -f "$MPC_VST/tools/$t" ] || { echo "need mpc-vst-plugins with tools/$t (MPC_VST)" >&2; exit 1; }
done
[ -n "${SKIP_BUILD:-}" ] || { ./build-sdk.sh test; ./build-sdk.sh; }
DIR="sd88me - VST - Mono-101"; SRC="build/$DIR"
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); sys.exit(0 if m["uid"]=="M101" and "Beta" not in m["name"] else "not the release identity")' "$SRC/plugin.json"
VER=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/plugin.json")
st="build/catalog/aarch64"; rm -rf "$st"; mkdir -p "$st/$DIR"
cp -r "$SRC/Plugin Skins" "$SRC/version.xml" "$st/$DIR/"
python3 - "$SRC/plugin.json" "$st/$DIR/plugin.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m.pop("file32", None)
m["file64"] = "mono101.so"
json.dump(m, open(sys.argv[2], "w"), indent=2)
PY
cp "$SRC/VST/mono101-arm64.so" "$st/mono101.so"
mkdir -p "$st/doc"; cp LICENSE "$st/doc/"   # AGPL-3.0: the licence and where the source is, with the binary
printf 'Mono-101 %s is free software under the GNU AGPL 3.0 (LICENSE).\nIt is a port of the Lemus SH-101 engine (https://github.com/lemus-dev/lemus, AGPL-3.0), modified.\nSource: https://github.com/sd88me/mpc-vst-mono101 (tag v%s)\n' "$VER" "$VER" > "$st/doc/SOURCE.txt"
printf '<PLUGIN name="Mono-101" descriptiveName="Mono-101" format="VST" category="Synth" manufacturer="sd88me" version="%s" file="mono101.so" uid="4d313031" isInstrument="1" fileTime="0" infoUpdateTime="0" numInputs="0" numOutputs="2" isShell="0"/>\n' "$VER" > "$st/entry.xml"
python3 "$MPC_VST/tools/release.py" --so "$st/mono101.so" --skin "$st/$DIR" --entry "$st/entry.xml" --version "$VER" \
  --extra "$st/doc:doc" --user-data mono101-presets.txt \
  --repo sd88me/mpc-vst-mono101 --license AGPL-3.0-only --id mono-101 \
  --about "A circuit-modelled SH-101 (the Lemus engine, ported): the manual's 40 sample sounds, user presets, Circuit Bent mods." \
  -o "$st/dist"
mkdir -p dist
z=$(ls "$st/dist"/*.zip); cp "$z" "dist/Mono-101-$VER-mpc-aarch64.zip"
python3 "$MPC_VST/tools/catalog_check.py" "dist/Mono-101-$VER-mpc-aarch64.zip" --catalog --expect-id mono-101 --expect-repo sd88me/mpc-vst-mono101
python3 "$MPC_VST/tools/sdk_zip.py" "dist/Mono-101-$VER-mpc-sdk.zip" "dist/Mono-101-$VER-mpc-aarch64.zip"
for f in "dist/Mono-101-$VER-mpc-aarch64.zip" "dist/Mono-101-$VER-mpc-sdk.zip"; do   # no ROM, no licensed font
  if python3 -I -m zipfile -l "$f" | grep -i -E '\.(bin|rom|syx|otf|ttf)\b'; then echo "refusing: a ROM-like or font file is in $f" >&2; exit 1; fi
done
(cd dist && sha256sum "Mono-101-$VER-mpc-aarch64.zip" "Mono-101-$VER-mpc-sdk.zip" > "Mono-101-$VER-SHA256SUMS.txt" && cat "Mono-101-$VER-SHA256SUMS.txt")
