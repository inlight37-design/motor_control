#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

set +u
source "${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
set -u
colcon build --packages-select soem epos_interfaces epos_control --cmake-args -DCMAKE_BUILD_TYPE=Release
