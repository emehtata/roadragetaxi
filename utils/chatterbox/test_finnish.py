import torch
import soundfile as sf
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using: {device}")

model = ChatterboxMultilingualTTS.from_pretrained(device=device)

text = """
Tervetuloa Radio Raivoon.
Tämä on päivän tärkein liikennetiedote.
Keskustan liikenne on tällä hetkellä erittäin ruuhkainen.
Jos olet liikkeellä autolla, kannattaa varata hieman ylimääräistä aikaa.
"""

wav = model.generate(text, language_id="fi")

sf.write(
    "test_finnish.wav",
    wav.squeeze(0).detach().cpu().numpy(),
    model.sr,
)

print("Generated: test_finnish.wav")
