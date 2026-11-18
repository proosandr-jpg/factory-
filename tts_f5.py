"""F5-TTS с клонированием голоса — русский файнтюн Misha24-10/F5-TTS_RUSSIAN.

Модель: flow-matching TTS, клонирует голос по референсному аудио (10–12 с)
и его транскрипту. Работает на CPU (torch), GPU не требуется.

Файлы модели лежат локально:
  assets/models/f5-russian/model_240000_inference.safetensors
  assets/models/f5-russian/vocab.txt
Референс:
  assets/voice/reference_12s.wav  + sidecar reference_12s.txt с транскриптом

Лицензия модели — CC BY-NC 4.0: некоммерческое использование.
"""

import os
import time
import wave

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "assets", "models", "f5-russian")
CKPT_PATH = os.path.join(MODEL_DIR, "model_240000_inference.safetensors")
VOCAB_PATH = os.path.join(MODEL_DIR, "vocab.txt")

REFERENCE_AUDIO = os.path.join(BASE_DIR, "assets", "voice", "reference_12s.wav")
REFERENCE_TEXT_FILE = os.path.join(BASE_DIR, "assets", "voice", "reference_12s.txt")

HF_REPO = "Misha24-10/F5-TTS_RUSSIAN"
HF_FILES = {
    CKPT_PATH: "F5TTS_v1_Base/model_240000_inference.safetensors",
    VOCAB_PATH: "F5TTS_v1_Base/vocab.txt",
}

_CACHE = {}


def _patch_audio_io():
    """Убрать зависимость от torchcodec: он требует разделяемые DLL FFmpeg.

    В этом окружении ffmpeg статический, поэтому ``torchaudio.load`` падает
    на импорте libtorchcodec_*.dll. Читаем и пишем звук через soundfile
    (он уже стоит вместе с f5-tts).
    """
    if _CACHE.get("audio_io_patched"):
        return
    import torch
    import torchaudio

    def load_via_soundfile(path, **kwargs):
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), sr

    def save_via_soundfile(path, tensor, sample_rate, **kwargs):
        import soundfile as sf
        array = tensor.detach().cpu().numpy()
        sf.write(str(path), array.T, int(sample_rate))

    torchaudio.load = load_via_soundfile
    torchaudio.save = save_via_soundfile
    _CACHE["audio_io_patched"] = True


class F5Error(RuntimeError):
    """Ошибка загрузки модели или синтеза."""


def _ensure_files():
    """Скачать чекпойнт и словарь, если их нет локально."""
    missing = {path: remote for path, remote in HF_FILES.items() if not os.path.exists(path)}
    if not missing:
        return
    try:
        from huggingface_hub import hf_hub_download
    except ModuleNotFoundError as exc:
        raise F5Error(
            "Нет huggingface_hub, а файлы модели отсутствуют.\n"
            "Установите: python -m pip install huggingface_hub"
        ) from exc

    os.makedirs(MODEL_DIR, exist_ok=True)
    for local_path, remote_name in missing.items():
        print(f"      скачивание {remote_name}…")
        cached = hf_hub_download(HF_REPO, remote_name)
        import shutil
        shutil.copy2(cached, local_path)


def reference_text(path=None):
    """Транскрипт референса: из env F5_REF_TEXT или sidecar .txt рядом с аудио."""
    env_text = os.environ.get("F5_REF_TEXT")
    if env_text:
        return env_text.strip()

    audio_path = path or REFERENCE_AUDIO
    sidecar = os.path.splitext(audio_path)[0] + ".txt"
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            return text

    raise F5Error(
        f"нет транскрипта референса: {sidecar}\n"
        "Он обязателен: F5-TTS клонирует голос по паре «аудио + его текст».\n"
        "Создайте файл или задайте переменную F5_REF_TEXT."
    )


def _load_model(device="cpu"):
    if "model" in _CACHE:
        return _CACHE["model"]

    _ensure_files()
    _patch_audio_io()
    try:
        from f5_tts.api import F5TTS
    except ModuleNotFoundError as exc:
        raise F5Error(
            "f5-tts не установлен.\n"
            "Установите: python -m pip install torch torchaudio "
            "--index-url https://download.pytorch.org/whl/cpu\n"
            "затем: python -m pip install --no-build-isolation f5-tts"
        ) from exc

    started = time.time()
    model = F5TTS(
        model="F5TTS_v1_Base",
        ckpt_file=CKPT_PATH,
        vocab_file=VOCAB_PATH,
        device=device,
    )
    print(f"      модель загружена за {time.time() - started:.1f} c")
    _CACHE["model"] = model
    return model


def synthesize(text, out_path, reference=None, ref_text=None,
               nfe_step=32, speed=1.0, seed=None):
    """Озвучить текст голосом из референса."""
    if not text or not text.strip():
        raise F5Error("пустой текст для озвучки")

    reference = reference or os.environ.get("F5_REF_AUDIO") or REFERENCE_AUDIO
    if not os.path.exists(reference):
        raise F5Error(f"нет референсного аудио: {reference}")

    ref_text = ref_text or reference_text(reference)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    model = _load_model()
    started = time.time()

    def quiet(*args, **kwargs):
        return None

    wav, sr, _spec = model.infer(
        ref_file=reference,
        ref_text=ref_text,
        gen_text=text.strip(),
        show_info=quiet,
        progress=None,
        nfe_step=nfe_step,
        speed=speed,
        seed=seed,
        file_wave=out_path,
    )
    elapsed = time.time() - started

    with wave.open(out_path) as f:
        duration = f.getnframes() / f.getframerate()

    return {
        "path": out_path,
        "backend": "f5-tts",
        "duration_sec": round(duration, 2),
        "elapsed_sec": round(elapsed, 1),
        "sample_rate": sr,
        "cloning": True,
        "reference": reference,
    }


def describe():
    ready = os.path.exists(CKPT_PATH) and os.path.exists(VOCAB_PATH)
    try:
        import f5_tts  # noqa: F401
        installed = True
    except ModuleNotFoundError:
        installed = False
    return {
        "installed": installed,
        "model_files": ready,
        "ckpt": CKPT_PATH,
        "reference": REFERENCE_AUDIO,
        "reference_text": os.path.exists(REFERENCE_TEXT_FILE),
        "license": "CC BY-NC 4.0 (некоммерческое использование)",
    }
