#!/usr/bin/env bash

# 用途：从 ns-3 根目录重复运行 VNDN 方格路网仿真，并记录 OBU、RSU、Router 日志。
# Purpose: Repeatedly run the VNDN grid-road simulation from the ns-3 project root
#          with OBU, RSU, and Router logging enabled.
#
# 用法：./scratch/vndn-grid-simulator/run-vndn-grid.sh <运行次数>
# Usage: ./scratch/vndn-grid-simulator/run-vndn-grid.sh <run-count>
#
# 每轮最多运行 300 秒；超时或失败后继续下一轮，Ctrl+C 会终止本轮及后续运行。
# Each run is limited to 300 seconds. Timeout/failure advances to the next run,
# while Ctrl+C terminates the current run and all remaining runs.

set -u

stop_script()
{
  echo
  echo "Interrupted; stopping all remaining runs."
  exit 130
}

trap stop_script INT TERM

if [[ $# -ne 1 || ! $1 =~ ^[1-9][0-9]*$ ]]; then
  echo "Usage: $0 <run-count>" >&2
  exit 2
fi

run_count=$1
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ns3_dir=$(cd "${script_dir}/../.." && pwd)
cd "${ns3_dir}" || exit 1

./waf build -j 4

for ((run_index = 1; run_index <= run_count; ++run_index)); do
  echo "[$run_index/$run_count] Starting vndn-grid-simulator (300-second limit)"
  NS_LOG=ndn.VndnObu:ndn.VndnRsu:ndn.VndnRouter \
    timeout --foreground 300s ./waf --run "vndn-grid-simulator --log"
  exit_code=$?

  if [[ $exit_code -eq 130 || $exit_code -eq 143 ]]; then
    stop_script
  elif [[ $exit_code -eq 124 ]]; then
    echo "[$run_index/$run_count] Timed out after 300 seconds"
  elif [[ $exit_code -ne 0 ]]; then
    echo "[$run_index/$run_count] Exited with code $exit_code"
  else
    echo "[$run_index/$run_count] Completed"
  fi
done
