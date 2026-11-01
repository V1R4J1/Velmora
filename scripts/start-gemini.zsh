#!/bin/zsh
set -eu
cd "${0:A:h:h}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  read -rs 'GEMINI_API_KEY?Gemini API key (input hidden): '
  print
fi
if [[ -z "$GEMINI_API_KEY" ]]; then
  print -u2 'A Gemini API key is required.'
  exit 1
fi
export GEMINI_API_KEY
export VELMORA_AI_ENABLED=1 VELMORA_AI_PROVIDER=gemini
exec .venv/bin/python -B -m flask --app app run --port 5055
