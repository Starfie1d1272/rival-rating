#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

export XDG_CACHE_HOME=/tmp/codex-xdg-cache
export MPLCONFIGDIR=/tmp/codex-mpl-cache
export PYTHONPATH=solo-clutch-trainer

exec .venv/bin/python -m solo_clutch_trainer.dust2_phase_c_train \
  --confirm-train \
  --run-dir .solo-clutch-runs/dust2-phase-c-20260609-v6 \
  --max-wall-seconds 21600 \
  --chunk-steps 4096 \
  --n-envs 2 \
  --max-envs 4 \
  --n-steps 128 \
  --batch-size 256 \
  --learning-rate 1e-4 \
  --ent-coef 0.03 \
  --checkpoint-cap-gb 7 \
  --history-limit 8 \
  --eval-episodes-per-seed 2 \
  --max-decisions 900
