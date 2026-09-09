# NVIDIA RTX 5060 / CUDA setup

This project is configured to run Chatterbox TTS locally using an NVIDIA RTX 5060 GPU with 8 GB VRAM.

The instructions below are intended for:

* NVIDIA RTX 5060 8 GB
* Windows + WSL2
* Ubuntu
* Python 3.12
* CUDA-enabled PyTorch
* Chatterbox Multilingual TTS

## 1. Check the GPU

Run this inside WSL2:

```bash
nvidia-smi
```

The NVIDIA GPU should be visible. NVIDIA drivers should **not** be installed separately inside WSL2. WSL2 uses the NVIDIA driver installed on Windows.

Check CUDA support from PyTorch:

```bash
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Expected result is similar to:

```text
2.11.0+cu128
12.8
True
NVIDIA GeForce RTX 5060
```

## 2. Create the Python virtual environment

Python 3.11 is recommended by the Chatterbox project, although Python 3.12 can also work.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

## 3. Install PyTorch with RTX 5060 support

The RTX 5060 uses a newer NVIDIA GPU architecture. Use a recent PyTorch build with CUDA 12.8 support.

Install:

```bash
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128
```

Verify:

```bash
python - <<'PY'
import torch

print("PyTorch:", torch.__version__)
print("CUDA:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print("Compute capability:", torch.cuda.get_device_capability(0))
PY
```

The RTX 5060 should report a CUDA architecture containing:

```text
(12, 0)
```

or:

```text
sm_120
```

## 4. Install Chatterbox without replacing PyTorch

**Important:** Do not install `chatterbox-tts` normally after installing the newer PyTorch version.

Some Chatterbox package versions specify older PyTorch dependencies. A normal installation can therefore downgrade PyTorch to a version that does not properly support the RTX 5060.

Install Chatterbox without modifying the existing PyTorch installation:

```bash
pip install --no-deps chatterbox-tts
```

Then install the required Python dependencies separately if necessary.

## 5. Verify GPU acceleration

Run:

```bash
python - <<'PY'
import torch

assert torch.cuda.is_available(), "CUDA is not available"

print("GPU:", torch.cuda.get_device_name(0))
print("CUDA:", torch.version.cuda)
print("PyTorch:", torch.__version__)

x = torch.randn(4096, 4096, device="cuda")
y = x @ x

torch.cuda.synchronize()

print("GPU computation OK")
PY
```

If this finishes without errors, PyTorch can execute CUDA workloads on the RTX 5060.

## 6. Generate Finnish speech

Example:

```python
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

wav = model.generate(
    text,
    language_id="fi",
)

sf.write(
    "test_finnish.wav",
    wav.squeeze(0).detach().cpu().numpy(),
    model.sr,
)

print("Generated: test_finnish.wav")
```

Install `soundfile` if necessary:

```bash
pip install soundfile
```

Using `soundfile` to write the WAV file avoids unnecessary TorchCodec/FFmpeg dependencies.

## 7. Important TorchCodec note

TorchCodec is **not required just to save generated Chatterbox audio as WAV**.

If `torchaudio.save()` produces errors involving:

```text
libtorchcodec
libnvrtc.so
libavutil.so
libnppicc.so
```

use `soundfile` instead:

```python
import soundfile as sf

sf.write(
    "output.wav",
    wav.squeeze(0).detach().cpu().numpy(),
    model.sr,
)
```

This keeps the audio generation pipeline independent of the system FFmpeg/CUDA multimedia libraries.

## 8. Do not downgrade PyTorch

Before installing or updating dependencies, check:

```bash
python -c "import torch; print(torch.__version__)"
```

For the RTX 5060 setup, keep a recent CUDA 12.8 PyTorch build.

In particular, avoid accidentally changing:

```text
torch 2.11.0+cu128
```

to:

```text
torch 2.6.x
```

Older PyTorch versions may not contain the required `sm_120` CUDA architecture support.

If a package tries to downgrade PyTorch, install that package with:

```bash
pip install --no-deps <package>
```

and install its Python dependencies separately.

## 9. Monitor GPU usage

While generating speech, open another WSL terminal or Windows terminal and run:

```bash
nvidia-smi
```

You should see Python using the RTX 5060.

For continuous monitoring:

```bash
watch -n 1 nvidia-smi
```

Typical useful information:

* GPU memory usage
* GPU utilization
* temperature
* power consumption
* running Python process

## 10. Check VRAM

The RTX 5060 has 8 GB VRAM.

Check available VRAM:

```bash
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free \
    --format=csv
```

Chatterbox can run on an 8 GB RTX 5060, but avoid loading multiple large models into GPU memory simultaneously.

If several models are used by the project, explicitly move unused models back to CPU or release them before loading another model.

## 11. Recommended environment

For reproducibility, the working configuration is:

```text
OS:             Windows + WSL2
Linux:          Ubuntu
GPU:            NVIDIA RTX 5060 8 GB
Python:         3.12
PyTorch:        2.11.x
PyTorch CUDA:   cu128
CUDA runtime:   12.8
Chatterbox:     chatterbox-tts
Device:         cuda
Audio output:   soundfile
```

Verify the complete setup with:

```bash
python - <<'PY'
import torch
import chatterbox

print("PyTorch:", torch.__version__)
print("CUDA:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print("Capability:", torch.cuda.get_device_capability(0))

print("Chatterbox import: OK")
PY
```

## 12. Troubleshooting

### `CUDA is not available`

Check:

```bash
nvidia-smi
```

If `nvidia-smi` does not work inside WSL2, check the NVIDIA driver installation on Windows and make sure WSL2 GPU support is enabled.

Then check:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

### `NVIDIA GeForce RTX 5060 is not compatible`

Check:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.get_arch_list())"
```

The architecture list should contain:

```text
sm_120
```

If it does not, the installed PyTorch version is too old.

Reinstall the CUDA 12.8 build:

```bash
pip uninstall -y torch torchvision torchaudio

pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128
```

### Chatterbox tries to install an old PyTorch

Do not allow pip to replace the working PyTorch installation.

Use:

```bash
pip install --no-deps chatterbox-tts
```

Then verify:

```bash
python -c "import torch; print(torch.__version__)"
```

### `libtorchcodec.so` / FFmpeg errors

If Chatterbox generates the audio successfully but saving fails with TorchCodec errors, do not debug TorchCodec unless it is actually needed.

Use:

```bash
pip install soundfile
```

and:

```python
import soundfile as sf

sf.write(
    "output.wav",
    wav.squeeze(0).detach().cpu().numpy(),
    model.sr,
)
```

### GPU works but generation is slow

Check GPU utilization:

```bash
nvidia-smi
```

If Python is using the GPU but utilization is low, this can be normal for parts of the TTS pipeline. Generation is not necessarily a continuous 100% GPU workload.

Make sure the model was loaded with:

```python
model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
```

and not:

```python
device="cpu"
```

## 13. Quick start

For a fresh installation:

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip

pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128

pip install --no-deps chatterbox-tts

pip install soundfile
```

Then verify:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.get_device_name(0))"
```

Expected:

```text
2.11.x+cu128
NVIDIA GeForce RTX 5060
```

Finally:

```bash
python test_finnish.py
```

The resulting WAV file can then be converted to OGG Vorbis for use in the game.
