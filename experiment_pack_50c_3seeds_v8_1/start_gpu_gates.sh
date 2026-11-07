#!/usr/bin/env bash
# Explicit opt-in: starts only two 50-client GPU calibration jobs.
set -euo pipefail
cd "$(dirname "$0")/.."
export DFL_RANGE_LIB="${DFL_RANGE_LIB:-$HOME/secure-dfl-protocol-v6/native/dfl_range/target/release/libdfl_range.so}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUBLAS_WORKSPACE_CONFIG=:4096:8
PY="${DFL_PYTHON:-$HOME/.venvs/secure-dfl-bench/bin/python}"
PACK=experiment_pack_50c_3seeds_v8_1
"$PY" scripts/pack_campaign.py status --pack "$PACK"
"$PY" scripts/pack_campaign.py preflight --pack "$PACK"
"$PY" scripts/pack_campaign.py run --pack "$PACK" \
  --work-root "$PWD/private-campaign" --data-cache "$PWD/data-cache" --until gpu_gate
