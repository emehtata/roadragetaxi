import argparse
import hashlib
import json
import os
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting shell variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def entry_hash(finnish_text: str) -> str:
    return hashlib.sha256(finnish_text.encode("utf-8")).hexdigest()[:16]


def update_hashes(data: dict) -> None:
    """Store one deterministic hash based on each Finnish sentence."""
    for entry in data.get("lines", []):
        finnish_text = entry.get("fi")
        if finnish_text:
            entry["hash"] = entry_hash(finnish_text)
        entry.pop("audio_hashes", None)


def voice_for(gender: str, language: str) -> str:
    defaults = {
        ("f", "fi"): "fi-FI-NooraNeural",
        ("m", "fi"): "fi-FI-HarriNeural",
        ("f", "en"): "en-US-JennyNeural",
        ("m", "en"): "en-US-GuyNeural",
    }
    return os.getenv("TTS_VOICE") or defaults[(gender, language)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Azure Speech WAV files for passenger chatter.")
    parser.add_argument("gender", choices=("f", "m"), help="Voice gender: f or m")
    parser.add_argument("json_path", type=Path, help="Path to passenger_chatter.json")
    parser.add_argument("language", nargs="?", default="fi", choices=("fi", "en"))
    parser.add_argument("--hash-only", action="store_true", help="Update JSON hashes without calling Azure Speech")
    args = parser.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    speech_key = os.getenv("SPEECH_KEY")
    service_region = os.getenv("SPEECH_REGION")
    if not speech_key or not service_region:
        missing = [
            name for name, value in (("SPEECH_KEY", speech_key), ("SPEECH_REGION", service_region)) if not value
        ]
        raise RuntimeError(f"Missing {', '.join(missing)} in utils/.env or the environment")

    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    update_hashes(data)
    args.json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.hash_only:
        print(f"Updated audio hashes in [{args.json_path}]")
        return

    for entry in data.get("lines", []):
        text = entry.get(args.language)
        if not text:
            continue
        audio_hash = entry["hash"]
        output_dir = Path(__file__).with_name("output")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{args.gender}_{args.language}_{audio_hash}.wav"
        if output_path.exists() and os.getenv("TTS_OVERWRITE", "false").lower() != "true":
            print(f"Skipping existing [{output_path}]")
            continue

        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        speech_config.speech_synthesis_voice_name = voice_for(args.gender, args.language)
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        result = synthesizer.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Generated [{output_path}]")
        else:
            details = result.cancellation_details
            raise RuntimeError(f"Speech synthesis failed for entry {entry['id']}: {details.reason} ({details.error_details})")


if __name__ == "__main__":
    main()
