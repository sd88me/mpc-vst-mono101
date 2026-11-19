#!/bin/sh
# x86, armhf (Force / Gen1) and aarch64 (Live III / Gen2) builds of the voice test harness, into tools/voicetest/.
# The armhf flags are the SDK build's for Gen1; aarch64 builds in the Welle/Xenia docker image if there is no cross g++.
set -e
cd "$(dirname "$0")"
L=../../src/lemus
SRC="vtest.cpp $(ls $L/*.cpp | tr '\n' ' ')"
INC="-I$L -I../../src/onex1"
g++ -O3 -std=c++17 $INC $SRC -o vtest
arm-linux-gnueabihf-g++ -O3 -std=c++17 -mcpu=cortex-a17 -mfpu=neon-vfpv4 -mfloat-abi=hard -static -Wno-psabi $INC $SRC -o vtest-arm32
if command -v aarch64-linux-gnu-g++ >/dev/null; then
  aarch64-linux-gnu-g++ -O3 -std=c++17 -mcpu=cortex-a76 -static $INC $SRC -o vtest-arm64
else
  R=$(cd ../.. && pwd)
  docker run --rm -u "$(id -u):$(id -g)" -v "$R":/b -w /b/tools/voicetest xenia-a64-builder \
    aarch64-linux-gnu-g++ -O3 -std=c++17 -mcpu=cortex-a76 -static $INC $SRC -o vtest-arm64
fi
