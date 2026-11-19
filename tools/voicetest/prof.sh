#!/bin/sh
# Sampling profile (pcprof.cpp) of the armhf harness on the Live III's A55 core 2, the closest to a Gen1
# core we can reach without the Force; FORCE=root@<ip> runs it there instead. Per function and per line.
#   prof.sh [WORKLOAD] [nfuncs] [nlines]
set -e
cd "$(dirname "$0")"
H=${FORCE:-${LIVE3:-root@192.168.2.217}}
T=${TMPDIR:-/tmp}/1x1prof; mkdir -p $T
L=../../src/lemus
arm-linux-gnueabihf-g++ -O3 -g -std=c++17 -mcpu=cortex-a17 -mfpu=neon-vfpv4 -mfloat-abi=hard -static -Wno-psabi -I$L -I../../src/onex1 \
  vtest.cpp $L/*.cpp pcprof.cpp -o $T/vpc
ssh $H 'mkdir -p /tmp/1x1prof'
scp -q $T/vpc $H:/tmp/1x1prof/vpc
timeout 600 ssh $H "cd /tmp/1x1prof && rm -f pcprof.txt && taskset -c 2 ./vpc time ${1:-} >/dev/null && cat pcprof.txt" > $T/pcprof.txt
awk '{print $2}' $T/pcprof.txt | arm-linux-gnueabihf-addr2line -f -C -e $T/vpc | paste - - > $T/pcsym.txt
paste -d' ' $T/pcprof.txt $T/pcsym.txt > $T/pcall.txt
TOTAL=$(awk '{s+=$1} END {print s}' $T/pcall.txt)
echo "== by function ($TOTAL samples)"
awk -v t=$TOTAL '{f=$3; c[f]+=$1} END {for (k in c) printf "%5.1f%% %s\n", 100*c[k]/t, k}' $T/pcall.txt | sort -rn | head -${2:-20}
echo "== by line"
awk -v t=$TOTAL '{n=split($NF,a,"/"); l=a[n]; sub(/ .*/,"",l); c[l]+=$1} END {for (k in c) printf "%5.1f%% %s\n", 100*c[k]/t, k}' $T/pcall.txt | sort -rn | head -${3:-30}
