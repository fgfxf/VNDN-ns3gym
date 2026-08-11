#!/usr/bin/env bash

# 用途：在 ns-3 项目根目录中连续运行指定次数的 VNDN 环形道路仿真，
#       并开启 OBU、RSU 和 Router 日志以及 ns-3 Visualizer。
# Purpose: Repeatedly run the VNDN circle-road simulation from the ns-3 project root,
#          with OBU, RSU, and Router logging plus the ns-3 Visualizer enabled.
#
# 用法：./scratch/vndn-circle-simulator/run-vndn-circle.sh <运行次数>
# Usage: ./scratch/vndn-circle-simulator/run-vndn-circle.sh <run-count>
#
# 每轮最多运行 80 秒；单轮超时或失败后继续下一轮，按 Ctrl+C 则终止全部运行。
# Each run is limited to 80 seconds. A timeout or failure advances to the next run,
# while Ctrl+C terminates the script and all remaining runs.

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

for ((run_index = 1; run_index <= run_count; ++run_index)); do
  echo "[$run_index/$run_count] Starting vndn-circle-simulator (80-second limit)"
  NS_LOG=ndn.VndnObu:ndn.VndnRsu:ndn.VndnRouter \
    timeout --foreground 80s ./waf --run "vndn-circle-simulator --log"
  exit_code=$?

  if [[ $exit_code -eq 130 || $exit_code -eq 143 ]]; then
    stop_script
  elif [[ $exit_code -eq 124 ]]; then
    echo "[$run_index/$run_count] Timed out after 80 seconds"
  elif [[ $exit_code -ne 0 ]]; then
    echo "[$run_index/$run_count] Exited with code $exit_code"
  else
    echo "[$run_index/$run_count] Completed"
  fi
done
