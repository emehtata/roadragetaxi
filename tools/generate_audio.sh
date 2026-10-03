#!/usr/bin/env bash
# Generate the game's sound effects from the audio catalog with Stable Audio Open.
# All arguments go to tools/generate_audio.py, e.g.:
#   tools/generate_audio.sh --dry-run
#   tools/generate_audio.sh --group weather.thunder
#   tools/generate_audio.sh --priority required
# AUDIO_STUDIO overrides where ai-audio-studio (and its .venv) lives.
set -euo pipefail

AUDIO_STUDIO="${AUDIO_STUDIO:-/home/ubuntu/work/ai-audio-studio}"
PYTHON="$AUDIO_STUDIO/.venv/bin/python"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -x "$PYTHON" ]]; then
    echo "No Python at $PYTHON - set AUDIO_STUDIO to the ai-audio-studio directory." >&2
    exit 1
fi

cd "$REPO"
exec "$PYTHON" tools/generate_audio.py "$@"
