#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

export XDG_CACHE_HOME=/tmp/codex-xdg-cache
export MPLCONFIGDIR=/tmp/codex-mpl-cache
export PYTHONPATH=solo-clutch-trainer

exec .venv/bin/python -m solo_clutch_trainer.dust2_phase_c_train \
  --confirm-train \
  --dry-run \
  --smoke-eval \
  --run-dir .solo-clutch-runs/dust2-phase-c9-c0-dry-20260612 \
  --bootstrap-t-checkpoint .solo-clutch-runs/dust2-phase-c-20260612-v8/checkpoints/t/history/phase-c-t-generation-00003.zip \
  --bootstrap-ct-checkpoint .solo-clutch-runs/dust2-phase-c-20260612-v8/checkpoints/ct/history/phase-c-ct-generation-00003.zip \
  --curriculum-stage C0 \
  --train-sides T \
  --chunk-steps 256 \
  --n-envs 2 \
  --max-envs 4 \
  --n-steps 128 \
  --batch-size 256 \
  --learning-rate 1e-4 \
  --ent-coef 0.03 \
  --checkpoint-cap-gb 7 \
  --history-limit 8 \
  --eval-episodes-per-seed 1 \
  --max-decisions 900 \
  --min-side-win-rate 0.45 \
  --min-unplanted-plant-rate 0.50 \
  --min-unplanted-t-win-rate 0.35
