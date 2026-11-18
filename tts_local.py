"""Локальная озвучка без облачных API.

Два движка:

* ``piper``   — русский, ONNX, CPU, без torch. Голос задаётся файлом модели
  (по умолчанию ``assets/voice/piper/ru_RU-dmitri-medium.onnx`` — голос CC0,
  коммерческое использование допустимо). Клонирования нет.
* ``kittentts`` — английский, ONNX. Клонирования нет, русского нет: внутри
  жёстко зашит espeak ``en-us``, а в словаре символов отсутствует кириллица.
  Дополнительно требует установленный в системе espeak-ng.

Клонирование голоса локально возможно только тяжёлыми моделями класса XTTS
(torch + ~2 ГБ весов) и с лицензией CPML, которая запрещает коммерческое
использование. Для аккаунта клиники это неприемлемо, поэтому по умолчанию
работает штатный русский голос.

Интерфейс: ``synthesize(text, out_path, backend="auto") -> dict``.
"""

import os
import wave

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PIPER_VOICE_DEFAULT = os.path.join(
    BASE_DIR, "assets", "voice", "piper", "ru_RU-dmitri-medium.onnx"
)
KITTEN_SAMPLE_RATE = 24000
KITTEN_VOICE_DEFAULT = "expr-voice-2-m"

SUPPORTED_LANGUAGES = {"piper": {"ru", "en"}, "kittentts": {"en"}}


class TTSError(RuntimeError):
    """Ошибка локального синтеза речи."""


def _env(name, default=""):
    return os.environ.get(name) or default


def describe():
    """Состояние движков для --check. Ничего не скачивает и не вызывает сеть."""
    report = {}

    model_path = _env("PIPER_VOICE", PIPER_VOICE_DEFAULT)
    report["piper"] = {
        "model": model_path,
        "model_exists": os.path.exists(model_path),
        "languages": sorted(SUPPORTED_LANGUAGES["piper"]),
        "cloning": False,
    }
    try:
        import piper  # noqa: F401
        report["piper"]["installed"] = True
    except ModuleNotFoundError:
        report["piper"]["installed"] = False

    try:
        import kittentts  # noqa: F401
        report["kittentts"] = {
            "installed": True,
            "languages": sorted(SUPPORTED_LANGUAGES["kittentts"]),
            "cloning": False,
            "note": "нужен системный espeak-ng; русский не поддерживается",
        }
    except ModuleNotFoundError:
        report["kittentts"] = {"installed": False, "languages": [], "cloning": False}

    return report


def _synthesize_piper(text, out_path, voice_path=None):
    try:
        from piper import PiperVoice
    except ModuleNotFoundError as exc:
        raise TTSError(
            "Piper не установлен. Установите: python -m pip install piper-tts"
        ) from exc

    model_path = voice_path or _env("PIPER_VOICE", PIPER_VOICE_DEFAULT)
    if not os.path.exists(model_path):
        raise TTSError(
            f"нет файла голоса Piper: {model_path}\n"
            "Скачать: python -m piper.download_voices ru_RU-dmitri-medium "
            "--data-dir assets/voice/piper"
        )

    voice = PiperVoice.load(model_path)
    with wave.open(out_path, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return out_path


def _synthesize_kitten(text, out_path, voice=None, language="ru"):
    if language != "en":
        raise TTSError(
            "KittenTTS не умеет по-русски: внутри зашит espeak en-us, а в словаре "
            "символов нет кириллицы. Для русского используйте backend='piper'."
        )
    try:
        import numpy as np
        from kittentts import KittenTTS
    except ModuleNotFoundError as exc:
        raise TTSError(
            "KittenTTS не установлен. Установите: python -m pip install kittentts"
        ) from exc

    try:
        model = KittenTTS()
    except RuntimeError as exc:
        raise TTSError(
            f"KittenTTS не запускается: {exc}. Нужен системный espeak-ng в PATH."
        ) from exc

    audio = np.asarray(model.generate(text, voice=voice or KITTEN_VOICE_DEFAULT))
    samples = np.clip(audio.flatten(), -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)

    with wave.open(out_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(KITTEN_SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return out_path


def resolve_backend(backend="auto", language="ru"):
    """Выбрать движок. auto: русский -> piper, английский -> kittentts."""
    if backend != "auto":
        if backend not in SUPPORTED_LANGUAGES:
            raise TTSError(f"неизвестный backend={backend!r}, доступны: piper, kittentts")
        if language not in SUPPORTED_LANGUAGES[backend]:
            raise TTSError(
                f"{backend} не поддерживает язык {language!r} "
                f"(поддерживает: {sorted(SUPPORTED_LANGUAGES[backend])})"
            )
        return backend
    return "piper" if language.startswith("ru") else "kittentts"


def synthesize(text, out_path, backend="auto", language="ru", voice=None):
    """Озвучить текст локально. Возвращает словарь с путём и движком."""
    if not text or not text.strip():
        raise TTSError("пустой текст для озвучки")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    chosen = resolve_backend(backend, language)

    if chosen == "piper":
        _synthesize_piper(text, out_path, voice)
    else:
        _synthesize_kitten(text, out_path, voice, language)

    with wave.open(out_path) as wav_file:
        duration = wav_file.getnframes() / wav_file.getframerate()

    return {
        "path": out_path,
        "backend": chosen,
        "duration_sec": round(duration, 2),
        "cloning": False,
    }
