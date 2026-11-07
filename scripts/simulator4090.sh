#!/usr/bin/env bash
# Explicit commands only. Default check never trains or installs packages.
set -euo pipefail
SIM4090_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SIM4090_PACK="$SIM4090_ROOT/simulator4090_scaling_pack_20261107"
SIM4090_CACHE="$SIM4090_ROOT/data/simulator50-cache"
SIM4090_PY="${SIM4090_PYTHON:-$SIM4090_ROOT/.venv4090/bin/python}"
export CUBLAS_WORKSPACE_CONFIG=:4096:8 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cd "$SIM4090_ROOT"
case "${1:-check}" in
  setup)
    if [[ ! -x "$SIM4090_PY" ]]; then
      if [[ -x /opt/anaconda3/bin/conda ]]; then
        /opt/anaconda3/bin/conda create --yes --prefix "$SIM4090_ROOT/.venv4090" python=3.12 pip
      elif command -v python3.12 >/dev/null; then
        python3.12 -m venv "$SIM4090_ROOT/.venv4090"
      else
        echo 'Python3.12 or conda required; no global environment will be modified.' >&2; exit 1
      fi
    fi
    "$SIM4090_PY" -c 'import sys; assert sys.version_info[:2] == (3,12), "Requires Python3.12"'
    "$SIM4090_PY" -m pip install --requirement requirements-simulator50.txt
    echo 'Isolated environment installed. Next: bash scripts/simulator4090.sh check'
    ;;
  check)
    "$SIM4090_PY" scripts/simulator50.py preflight --pack "$SIM4090_PACK"
    "$SIM4090_PY" scripts/simulator50.py prepare-data --pack "$SIM4090_PACK" --cache "$SIM4090_CACHE"
    "$SIM4090_PY" scripts/simulator50_status.py --pack "$SIM4090_PACK"
    ;;
  calibrate)
    "$SIM4090_PY" scripts/simulator50.py calibrate --pack "$SIM4090_PACK" --cache "$SIM4090_CACHE" --topologies "${2:-ring,caveman,barabasi_albert}"
    ;;
  plan)
    "$SIM4090_PY" scripts/simulator50.py plan --pack "$SIM4090_PACK"
    ;;
  run)
    "$SIM4090_PY" scripts/simulator50.py run --pack "$SIM4090_PACK" --cache "$SIM4090_CACHE"
    ;;
  status)
    "$SIM4090_PY" scripts/simulator50_status.py --pack "$SIM4090_PACK"
    ;;
  summarize)
    "$SIM4090_PY" scripts/simulator50.py summarize --pack "$SIM4090_PACK"
    ;;
  pause)
    touch "$SIM4090_PACK/pause.request"
    echo 'Pause requested; the current round finishes and saves its checkpoint.'
    ;;
  clear-pause)
    "$SIM4090_PY" - "$SIM4090_PACK" <<'PY'
import sys
from pathlib import Path
pack=Path(sys.argv[1]).resolve()
for p in [pack/'pause.request',*pack.glob('calibration/cal-*/pause.request'),*pack.glob('results/sim-*/pause.request')]:
    assert p.resolve().is_relative_to(pack)
    if p.exists():p.unlink()
print('Pause flags cleared; no training started. Use calibrate or run explicitly. Original deadline preserved.')
PY
    ;;
  *) echo 'Usage: bash scripts/simulator4090.sh [setup|check|calibrate [topologies]|plan|run|status|summarize|pause|clear-pause]' >&2; exit 2 ;;
esac
