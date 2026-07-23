#!/usr/bin/env bash
set -euo pipefail
cd /root/captcha-solver
export PYTHONUNBUFFERED=1
export CAPTCHA_SOLVER_HOST="${CAPTCHA_SOLVER_HOST:-127.0.0.1}"
export CAPTCHA_SOLVER_PORT="${CAPTCHA_SOLVER_PORT:-5080}"
export CAPTCHA_SOLVER_THREAD="${CAPTCHA_SOLVER_THREAD:-1}"
export CAPTCHA_SOLVER_HEADLESS="${CAPTCHA_SOLVER_HEADLESS:-true}"
# Never inherit accidental MOCK=true from a developer shell into production PM2
if [[ "${CAPTCHA_SOLVER_FORCE_REAL:-}" == "1" ]]; then
  export CAPTCHA_SOLVER_MOCK_SOLVER=false
fi
exec .venv/bin/uvicorn app.main:app --host "$CAPTCHA_SOLVER_HOST" --port "$CAPTCHA_SOLVER_PORT"
