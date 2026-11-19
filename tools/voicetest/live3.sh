#!/bin/sh
# Copy the arm64 (and armhf) harness to the Live III, check it against the goldens there and time it:
# best of 3 on an A55 (core 2) and an A76 (core 5). ARCH=arm32 times the Gen1 build (AArch32 on the Live III).
set -e
cd "$(dirname "$0")"
L=${LIVE3:-root@192.168.2.217}
B=vtest-${ARCH:-arm64}
ssh $L 'mkdir -p /nvme/1x1-bench/golden'
scp -q $B $L:/nvme/1x1-bench/vtest
[ -n "$GOLDEN" ] && scp -q golden/*.f32 $L:/nvme/1x1-bench/golden/
timeout 900 ssh $L "cd /nvme/1x1-bench && ./vtest check golden | cut -c1-60
for c in 2 5; do echo \"--- core \$c\"; for r in 1 2 3; do taskset -c \$c ./vtest time; done | sort -k1,1 -k3,3n | awk '!s[\$1]++'; done"
