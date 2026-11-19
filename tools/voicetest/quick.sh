#!/bin/sh
# One timing pass of the current arm64 and armhf harness on the Live III's A55 core 2 (playing-workload mean, and bright/automation p99).
cd "$(dirname "$0")"
L=${LIVE3:?set LIVE3=root@<device address>}
scp -q vtest-arm64 $L:/nvme/1x1-bench/v64 && scp -q vtest-arm32 $L:/nvme/1x1-bench/v32
timeout 580 ssh $L 'cd /nvme/1x1-bench; for b in v64 v32; do taskset -c 2 ./$b time > t.$b; echo "$b A55: $(tail -1 t.$b | cut -d: -f2) | $(grep -E "^(bright|automation)" t.$b | awk "{printf \"%s p99 %s  \", \$1, \$6}")"; done'
