#!/bin/bash
# Build/test only. Release packaging signs the result inside-out.
set -euo pipefail
cd "$(dirname "$0")"
[[ ( $# == 2 || $# == 3 || $# == 4 ) && "${2:-}" =~ ^[a-f0-9]{64}$ &&
   "${3:-arm64}" =~ ^(arm64|x86_64)$ && ( $# != 4 || "${4:-}" == development-cross-compile ) ]] || {
  echo 'Usage: build.sh <build directory> <source-tree SHA256> [arm64|x86_64] [development-cross-compile]' >&2
  exit 2
}
mode="${4:-native}"
if [[ "$mode" == development-cross-compile ]]; then
  [[ "$(uname -s)" == Darwin && "$(uname -m)" == x86_64 && "$3" == arm64 ]] || { echo 'Development cross-compilation requires an Intel Mac and arm64 target' >&2; exit 2; }
fi
cmake -S . -B "$1" -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES="${3:-arm64}" -DOINK_PLUGIN_GIT_SHA="$2"
python3 check-licenses.py "$1"
cmake --build "$1" --parallel 2
if [[ "$mode" == development-cross-compile ]]; then
  echo 'Native HAL tests not run: cross-compilation (loopback, driver-identity)'
  ctest --test-dir "$1" --output-on-failure --exclude-regex '^(loopback|driver-identity)$'
else
  ctest --test-dir "$1" --output-on-failure
fi
