#!/usr/bin/env bash
# ./ai-audio.sh "Two harsh crow caws" [--seconds 5] [--seed 123]
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
studio_dir="${AUDIO_STUDIO:-$(dirname -- "$repo_dir")/ai-audio-studio}"
studio_python="$studio_dir/.venv/bin/python"
if [[ ! -x "$studio_python" ]]; then
    echo "No Python at $studio_python; set AUDIO_STUDIO to your ai-audio-studio directory." >&2
    exit 1
fi
exec "$studio_python" "$repo_dir/tools/ai_audio.py" --output-dir "$studio_dir/outputs" "$@"
