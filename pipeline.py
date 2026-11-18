"""Фабрика видео: сценарий -> локальная озвучка -> Agnes Video 2.5 / HeyGen -> готовый mp4.

Replicate больше не используется нигде:
  * озвучка — локальный TTS (F5-TTS с клонированием, Piper в резерве);
  * видео — Agnes Video 2.5 Flash через agnes_queue.py
    ИЛИ HeyGen (говорящая голова с lip-sync) через heygen_client.py.
Ни один шаг не обращается к api.replicate.com.

Запуск:
    python pipeline.py --check --text-file scenarios/01-bez-pokazaniy.txt
    python pipeline.py --text-file scenarios/01-bez-pokazaniy.txt
    python pipeline.py --video-engine heygen --heygen-audio-url https://.../audio.wav
    python pipeline.py --only video --audio output/audio/xxx.wav
    python pipeline.py --mock

Только стандартная библиотека + ffmpeg в PATH.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

# Этот интерпретатор работает с safe_path: папка скрипта не попадает в sys.path.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agnes_queue import AgnesError, MODEL_FLASH, VIDEO_MODELS, FlashQueueClient, estimate_cost  # noqa: E402
from heygen_client import HeyGenClient, HeyGenError as HGError  # noqa: E402
import tts_f5  # noqa: E402
import tts_local  # noqa: E402

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
VIDEO_DIR = os.path.join(OUTPUT_DIR, "video")
WORK_DIR = os.path.join(OUTPUT_DIR, "_work")


def _load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = _load_env(os.path.join(BASE_DIR, ".env"))

AVATAR_IMAGE = os.path.join(BASE_DIR, ENV.get("AVATAR_IMAGE", "assets/avatar.png"))
TTS_LANGUAGE = ENV.get("TTS_LANGUAGE", "ru")
# По умолчанию F5-TTS с клонированием голоса; piper — запасной вариант без клона.
TTS_BACKEND = ENV.get("TTS_BACKEND", "f5")

AGNES_VIDEO_MODEL = ENV.get("AGNES_VIDEO_MODEL", MODEL_FLASH)
# Agnes принимает длительность только в диапазоне 4–12 секунд.
AGNES_MIN_SECONDS = 4
AGNES_MAX_SECONDS = 12

# HeyGen: говорящая голова с lip-sync. Аватар создаётся один раз и повторно используется.
HEYGEN_VIDEO_MODEL = "heygen"
HEYGEN_ASPECT_RATIO = "9:16"
HEYGEN_AVATAR_NAME = "Doctor Avatar"

DEFAULT_SCENE_PROMPT = (
    "A calm middle-aged doctor in a white medical coat speaks to the camera in a "
    "bright modern clinic, soft daylight, shallow depth of field, stable camera, "
    "cinematic 3D style, vertical composition."
)
DEFAULT_TOPIC = "Почему я не делаю операцию без показаний"

AVATAR_PROMPT = (
    "Transform this person into a friendly semi-cartoon 3D doctor character, "
    "preserve facial features, glasses and hairstyle for likeness. Half-body shot "
    "from the waist up, looking straight into the camera, calm confident expression, "
    "clean white medical coat over a light shirt, stethoscope, soft studio lighting, "
    "bright neutral clinic background, high detail 3D render, vertical composition."
)


# --------------------------------------------------------------------------
# Шаг 1. Сценарий
# --------------------------------------------------------------------------
def generate_script(topic: str) -> str:
    """Сценарий по теме.

    MOCK: LLM-ключа нет, возвращаем шаблонную строку.
    Когда появится ключ — здесь будет запрос к OpenAI-совместимому API:

        POST {LLM_BASE_URL}/chat/completions
        {"model": ..., "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},   # skills/reels-scenarist
            {"role": "user", "content": topic}]}
    """
    # TODO(LLM): заменить заглушку, сигнатуру не менять.
    return f"Сценарий на тему: {topic}"


# --------------------------------------------------------------------------
# Вспомогательное: ffmpeg
# --------------------------------------------------------------------------
def _run(cmd):
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg вернул {proc.returncode}:\n{' '.join(cmd)}\n{proc.stderr[-1200:]}"
        )
    return proc


def probe_duration(path):
    proc = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    return float(proc.stdout.strip())


def _has_audio_stream(path):
    proc = _run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=index", "-of", "csv=p=0", path])
    return bool(proc.stdout.strip())


def split_audio(path, max_seconds=AGNES_MAX_SECONDS):
    """Порезать аудио на куски не длиннее max_seconds (лимит Agnes)."""
    total = probe_duration(path)
    if total <= max_seconds:
        return [path]
    parts = []
    for i in range(math.ceil(total / max_seconds)):
        start = i * max_seconds
        length = min(max_seconds, total - start)
        if length < 1.0:
            continue
        part = os.path.join(WORK_DIR, f"seg_{i:02d}.wav")
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
              "-i", path, "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", part])
        parts.append(part)
    return parts


def _with_silent_audio(path):
    """Добавить пустую дорожку, если клип без звука — иначе concat рвётся."""
    if _has_audio_stream(path):
        return path
    out = os.path.join(WORK_DIR, "silent_" + os.path.basename(path))
    duration = probe_duration(path)
    _run(["ffmpeg", "-y", "-v", "error", "-i", path,
          "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
          "-shortest", out])
    return out


def concat_mixed(paths, dest, width=1080, height=1920, fps=25):
    """Склейка клипов разного размера и без звука: кадр и дорожка нормализуются."""
    prepared = [_with_silent_audio(path) for path in paths]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for path in prepared:
        cmd += ["-i", path]

    filters = []
    for i in range(len(prepared)):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]"
        )
        filters.append(f"[{i}:a]aresample=48000[a{i}]")
    chain = "".join(f"[v{i}][a{i}]" for i in range(len(prepared)))
    filters.append(f"{chain}concat=n={len(prepared)}:v=1:a=1[v][a]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dest]
    _run(cmd)
    return dest


def mux_audio(video_path, audio_path, dest):
    """Наложить нашу озвучку на сгенерированную сцену.

    Agnes делает видео длиной 4–12 с и со своим звуком; здесь её дорожка
    заменяется нашей, а если картинка короче речи — последний кадр дотягивается.
    """
    video_dur = probe_duration(video_path)
    audio_dur = probe_duration(audio_path)
    padded = video_path

    if video_dur < audio_dur - 0.05:
        padded = os.path.join(WORK_DIR, "padded_" + os.path.basename(video_path))
        _run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
              "-vf", f"tpad=stop_mode=clone:stop_duration={audio_dur - video_dur:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-an", padded])

    _run(["ffmpeg", "-y", "-v", "error", "-i", padded, "-i", audio_path,
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-t", f"{audio_dur:.3f}", "-movflags", "+faststart", dest])
    return dest


# --------------------------------------------------------------------------
# Шаг 2. Озвучка (локально)
# --------------------------------------------------------------------------
def generate_audio(text, mock=False, backend=None):
    """Озвучить текст. По умолчанию — F5-TTS с клонированием из reference.wav."""
    if mock:
        print("      MOCK: файл не создаётся")
        return "mock_audio.mp3"

    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    out = os.path.join(AUDIO_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}.wav")
    chosen = (backend or TTS_BACKEND).lower()

    if chosen in ("f5", "auto"):
        print("      движок: F5-TTS (клонирование из reference.wav)")
        result = tts_f5.synthesize(text, out)
        print(f"      аудио: {result['path']} ({result['duration_sec']} c, "
              f"синтез {result['elapsed_sec']} c)")
        return result["path"]

    result = tts_local.synthesize(text, out, backend=chosen, language=TTS_LANGUAGE)
    print(f"      движок: {result['backend']} (клонирование: {result['cloning']})")
    print(f"      аудио: {result['path']} ({result['duration_sec']} c)")
    return result["path"]


# --------------------------------------------------------------------------
# Шаг 3. Видео (Agnes Video 2.5)
# --------------------------------------------------------------------------
def generate_video(audio_path, prompt=None, mock=False, size="720P",
                   dry_run=False, seed=0, model=None):
    """Сгенерировать сцену под нашу озвучку. Возвращает путь к mp4.

    Повторы при перегрузке очереди Agnes живут в QueueRetryClient:
    30 / 60 / 120 / 120 секунд, всего 5 попыток.
    """
    if mock:
        print("      MOCK: файл не создаётся")
        return "mock_video.mp4"
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"нет аудио: {audio_path}")

    model = model or AGNES_VIDEO_MODEL
    prompt = prompt or DEFAULT_SCENE_PROMPT
    duration = probe_duration(audio_path)
    segments = split_audio(audio_path, AGNES_MAX_SECONDS)
    print(f"      аудио {duration:.1f} c -> {len(segments)} клип(ов) Agnes ({model})")

    client = FlashQueueClient(dry_run=dry_run)
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)

    clips = []
    for i, segment in enumerate(segments, 1):
        segment_dur = probe_duration(segment)
        seconds = max(AGNES_MIN_SECONDS,
                      min(AGNES_MAX_SECONDS, int(math.ceil(segment_dur))))
        clip = os.path.join(WORK_DIR, f"agnes_{i:02d}.mp4")
        print(f"      клип {i}/{len(segments)}: {seconds} c, {size}")
        result = client.generate(
            prompt, clip,
            mode="text", seconds=seconds, size=size,
            aspect_ratio="9:16", seed=seed, model=model,
        )
        if result is None:
            print("      DRY-RUN: файл не создаётся")
            return None
        clips.append(result)

    visual = clips[0] if len(clips) == 1 else concat_mixed(
        clips, os.path.join(WORK_DIR, "agnes_visual.mp4")
    )
    final = os.path.join(VIDEO_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}.mp4")
    mux_audio(visual, audio_path, final)
    print(f"      видео: {final} ({probe_duration(final):.1f} c)")


# --------------------------------------------------------------------------
# Шаг 3. Видео (HeyGen — говорящая голова с lip-sync)
# --------------------------------------------------------------------------
def generate_video_heygen(audio_path, avatar_id=None, mock=False,
                          dry_run=False, audio_url=None, script=None,
                          voice_id=None, aspect_ratio=HEYGEN_ASPECT_RATIO,
                          avatar_name=HEYGEN_AVATAR_NAME):
    """Сгенерировать видео с говорящей головой через HeyGen.

    Поток:
      1. Если avatar_id не задан — загрузить фото аватара, создать фото-аватар,
         дождаться его готовности.
      2. Создать задачу видео (с audio_url или script+voice_id).
      3. Дождаться завершения, скачать mp4.

    Для lip-sync под ваше собственное аудио нужен публично доступный URL
    аудиофайла (HeyGen не забирает файлы с localhost). Передайте его через
    --heygen-audio-url, либо используйте script + voice_id (встроенный TTS
    HeyGen, голос не клонирован).
    """
    if mock:
        print("      MOCK: файл не создаётся")
        return "mock_video.mp4"
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"нет аудио: {audio_path}")

    try:
        client = HeyGenClient(dry_run=dry_run)
    except HGError as exc:
        raise HeyGenError(str(exc)) from exc

    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    # --- аватар -----------------------------------------------------------
    if not avatar_id:
        print(f"      HeyGen: аватар не задан, создаём из {AVATAR_IMAGE}")
        if not os.path.exists(AVATAR_IMAGE):
            raise FileNotFoundError(f"нет фото аватара: {AVATAR_IMAGE}")
        asset_id = client.upload_asset(AVATAR_IMAGE)
        avatar_id = client.create_avatar(asset_id, name=avatar_name)
        client.wait_avatar(avatar_id)
    else:
        print(f"      HeyGen: используем существующий аватар {avatar_id}")

    # --- видео ------------------------------------------------------------
    duration = probe_duration(audio_path)
    print(f"      аудио {duration:.1f} c -> HeyGen видео ({aspect_ratio})")

    video_path = os.path.join(VIDEO_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}.mp4")
    result = client.generate(
        avatar_id=avatar_id, out_path=video_path,
        audio_url=audio_url, script=script, voice_id=voice_id,
        aspect_ratio=aspect_ratio,
    )
    if result is None:
        print("      DRY-RUN: файл не создаётся")
        return None
    print(f"      видео: {video_path} ({probe_duration(video_path):.1f} c)")
    return video_path


# --------------------------------------------------------------------------
# Шаг 3. Видео (Agnes Video 2.5)
# --------------------------------------------------------------------------
def generate_video(audio_path, prompt=None, mock=False, size="720P",
                   dry_run=False, seed=0, model=None):
    """Сгенерировать сцену под нашу озвучку. Возвращает путь к mp4.

    Повторы при перегрузке очереди Agnes живут в QueueRetryClient:
    30 / 60 / 120 / 120 секунд, всего 5 попыток.
    """
    if mock:
        print("      MOCK: файл не создаётся")
        return "mock_video.mp4"
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"нет аудио: {audio_path}")

    model = model or AGNES_VIDEO_MODEL
    prompt = prompt or DEFAULT_SCENE_PROMPT
    duration = probe_duration(audio_path)
    segments = split_audio(audio_path, AGNES_MAX_SECONDS)
    print(f"      аудио {duration:.1f} c -> {len(segments)} клип(ов) Agnes ({model})")

    client = FlashQueueClient(dry_run=dry_run)
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)

    clips = []
    for i, segment in enumerate(segments, 1):
        segment_dur = probe_duration(segment)
        seconds = max(AGNES_MIN_SECONDS,
                      min(AGNES_MAX_SECONDS, int(math.ceil(segment_dur))))
        clip = os.path.join(WORK_DIR, f"agnes_{i:02d}.mp4")
        print(f"      клип {i}/{len(segments)}: {seconds} c, {size}")
        result = client.generate(
            prompt, clip,
            mode="text", seconds=seconds, size=size,
            aspect_ratio="9:16", seed=seed, model=model,
        )
        if result is None:
            print("      DRY-RUN: файл не создаётся")
            return None
        clips.append(result)

    visual = clips[0] if len(clips) == 1 else concat_mixed(
        clips, os.path.join(WORK_DIR, "agnes_visual.mp4")
    )
    final = os.path.join(VIDEO_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}.mp4")
    mux_audio(visual, audio_path, final)
    print(f"      видео: {final} ({probe_duration(final):.1f} c)")
    return final
    return final


# --------------------------------------------------------------------------
# Аватар (Agnes, картинки)
# --------------------------------------------------------------------------
def generate_avatar_agnes(source_photo=None, out_path=None):
    """Сделать 9:16-аватар через agnes_client.py (генерация картинок, не Replicate)."""
    try:
        from agnes_client import AgnesClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Для генерации аватара нужны requests и python-dotenv.\n"
            "Установите: python -m pip install requests python-dotenv"
        ) from exc

    source = source_photo or AVATAR_IMAGE
    if not os.path.exists(source):
        raise FileNotFoundError(f"нет референсного фото: {source}")

    out = out_path or os.path.join(os.path.dirname(AVATAR_IMAGE), "avatar_916.png")
    try:
        client = AgnesClient()
    except ValueError as exc:
        raise RuntimeError(
            f"{exc}\nДобавьте AGNES_API_KEY и AGNES_BASE_URL в .env (.env.example)."
        ) from exc

    print(f"      Agnes: генерация аватара по референсу {os.path.basename(source)}")
    path, status = client.generate_and_save(
        prompt=AVATAR_PROMPT, reference_image_path=source,
        output_path=out, size="2K", ratio="9:16",
    )
    print(f"      аватар: {path} (HTTP {status})")
    return path


# --------------------------------------------------------------------------
# Проверки без платных вызовов
# --------------------------------------------------------------------------
def preflight(text_file=None):
    problems = []
    print("Проверка окружения:")
    print("  Replicate API: не используется (0 обращений)")

    for tool in ("ffmpeg", "ffprobe"):
        ok = bool(shutil.which(tool))
        print(f"  {tool}: {'OK' if ok else 'НЕ НАЙДЕН'}")
        if not ok:
            problems.append(f"{tool} не в PATH")

    f5 = tts_f5.describe()
    print(f"  TTS f5-tts: установлен={f5['installed']}, "
          f"файлы модели={'есть' if f5['model_files'] else 'НЕТ'}")
    print(f"      референс: {f5['reference']}")
    print(f"      транскрипт референса: {'есть' if f5['reference_text'] else 'НЕТ'}")
    print(f"      лицензия: {f5['license']}")

    engines = tts_local.describe()
    piper = engines["piper"]
    print(f"  TTS piper (запасной, без клона): установлен={piper['installed']}, "
          f"голос={'есть' if piper['model_exists'] else 'НЕТ'}")
    if not (f5["installed"] and f5["model_files"] and f5["reference_text"]):
        print("      внимание: F5-TTS не готов — озвучка упадёт, пока не готовы модель и транскрипт")
        problems.append("F5-TTS не готов к работе")

    agnes_key = os.environ.get("AGNES_API_KEY") or ENV.get("AGNES_API_KEY", "")
    model_name = AGNES_VIDEO_MODEL
    profile = VIDEO_MODELS.get(model_name, {})
    if agnes_key:
        print(f"  Agnes: ключ есть (len {len(agnes_key)}), "
              f"base {ENV.get('AGNES_BASE_URL', 'https://apihub.agnes-ai.com/v1')}")
        print(f"      модель: {model_name} — {profile.get('notes', '')}")
        sizes = sorted(profile.get("sizes") or [])
        if sizes:
            print(f"      допустимые size: {', '.join(sizes)}")
    else:
        print("  Agnes: ключа нет — видео не сгенерируется")
        problems.append("нет AGNES_API_KEY")

    hg_key = os.environ.get("HEYGEN_API_KEY") or ENV.get("HEYGEN_API_KEY", "")
    if hg_key:
        print(f"  HeyGen: ключ есть (len {len(hg_key)}), "
              f"base {ENV.get('HEYGEN_BASE_URL', 'https://api.heygen.com/v3')}")
    else:
        print("  HeyGen: ключа нет — видео через HeyGen не сгенерируется")
        problems.append("нет HEYGEN_API_KEY")

    if text_file and os.path.exists(text_file):
        with open(text_file, encoding="utf-8") as f:
            text = f.read().strip()
        # Ориентир: ~14 символов в секунду русской речи у Piper.
        approx = len(text) / 14
        segments = max(1, math.ceil(approx / AGNES_MAX_SECONDS))
        per_clip = min(AGNES_MAX_SECONDS, max(AGNES_MIN_SECONDS, approx / segments))
        print(f"  текст: {len(text)} символов ~{approx:.0f} c речи "
              f"-> {segments} клип(ов) Agnes")
        print(f"      оценка: ~${estimate_cost(per_clip * segments):.2f} "
              f"({model_name})")

    if problems:
        print("\nПРОБЛЕМЫ:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nВсё готово к прогону.")
    return 0


# --------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Фабрика видео: сценарий -> локальная озвучка -> Agnes Video 2.5"
    )
    parser.add_argument("topic", nargs="?", default=DEFAULT_TOPIC, help="тема ролика")
    parser.add_argument("--text-file", help="файл с готовым текстом сценария")
    parser.add_argument("--only", choices=["all", "audio", "video"], default="all")
    parser.add_argument("--audio", help="готовое аудио для шага video")
    parser.add_argument("--image", default=AVATAR_IMAGE, help="картинка аватара")
    parser.add_argument("--mock", action="store_true", help="прогон без платных вызовов")
    parser.add_argument("--check", action="store_true", help="проверки без платных вызовов")

    parser.add_argument("--tts", choices=["auto", "f5", "piper", "kittentts"], default=None,
                        help="движок озвучки: f5 (клонирование) по умолчанию, piper — запасной")
    parser.add_argument("--language", default=None, help="язык озвучки, по умолчанию ru")
    parser.add_argument("--scene-prompt", help="промпт сцены для Agnes")
    parser.add_argument("--scene-size", default="720P", choices=["720P", "1080P", "1K", "2K"],
                        help="flash умеет только 720P")
    parser.add_argument("--video-model", default=None,
                        choices=sorted(VIDEO_MODELS), help="модель Agnes (по умолчанию flash)")
    parser.add_argument("--seed", type=int, default=0, help="seed Agnes для повторяемости")
    parser.add_argument("--agnes-dry-run", action="store_true",
                        help="показать тело запроса Agnes без отправки")

    # --- HeyGen -----------------------------------------------------------
    parser.add_argument("--video-engine", choices=["agnes", "heygen", "auto"],
                        default="auto", help="движок видео: agnes / heygen / auto (Agnes в приоритете, при ошибке — HeyGen)")
    parser.add_argument("--heygen-avatar-id", help="уже созданный avatar_id HeyGen (пропускает создание аватара)")
    parser.add_argument("--heygen-audio-url", help="публичный URL аудио для lip-sync (требуется для собственного аудио)")
    parser.add_argument("--heygen-script", help="текст для HeyGen TTS (вместо своего аудио)")
    parser.add_argument("--heygen-voice-id", help="voice_id HeyGen (требуется с --heygen-script)")
    parser.add_argument("--heygen-dry-run", action="store_true",
                        help="показать тело запроса HeyGen без отправки")

    parser.add_argument("--make-avatar", action="store_true",
                        help="сгенерировать 9:16-аватар через agnes_client.py")
    parser.add_argument("--avatar-photo", help="референсное фото для аватара")
    parser.add_argument("--avatar-out", help="куда сохранить аватар")
    args = parser.parse_args()

    if args.language:
        global TTS_LANGUAGE
        TTS_LANGUAGE = args.language

    if args.check:
        return preflight(args.text_file)

    if args.make_avatar:
        path = generate_avatar_agnes(args.avatar_photo, args.avatar_out)
        print(f"Аватар готов: {path}")
        return 0

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    started = time.time()

    print("=" * 66)
    print("ФАБРИКА ВИДЕО" + (" (MOCK)" if args.mock else ""))
    print("=" * 66)

    script = ""
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            script = f.read().strip()
        print(f"Сценарий: из файла {args.text_file} ({len(script)} символов)")
    elif args.only != "video":
        script = generate_script(args.topic)
        print(f"Сценарий: {script}")

    audio_path = args.audio
    if args.only in ("all", "audio"):
        print("-" * 66)
        print("[2/3] Озвучка (локально)")
        audio_path = generate_audio(script, mock=args.mock, backend=args.tts)
    elif not audio_path:
        parser.error("для --only video нужен --audio")

    video_path = None
    if args.only in ("all", "video"):
        print("-" * 66)
        engine = args.video_engine
        if engine == "auto":
            engine = "agnes"  # Agnes в приоритете
        print(f"[3/3] Видео ({engine.upper()})")
        if engine == "heygen":
            video_path = generate_video_heygen(
                audio_path,
                avatar_id=args.heygen_avatar_id,
                mock=args.mock,
                dry_run=args.heygen_dry_run or args.agnes_dry_run,
                audio_url=args.heygen_audio_url,
                script=args.heygen_script,
                voice_id=args.heygen_voice_id,
                aspect_ratio=HEYGEN_ASPECT_RATIO,
            )
        else:
            video_path = generate_video(
                audio_path, args.scene_prompt, mock=args.mock,
                size=args.scene_size, dry_run=args.agnes_dry_run, seed=args.seed,
                model=args.video_model,
            )

    result = {
        "status": "ok",
        "topic": args.topic,
        "script": script,
        "audio_path": audio_path,
        "video_path": video_path,
        "tts": {"backend": args.tts or TTS_BACKEND,
                "cloning": (args.tts or TTS_BACKEND) in ("f5", "auto")},
        "models": {"video": (args.video_model or AGNES_VIDEO_MODEL)
                   if args.video_engine != "heygen" else "heygen"},
        "video_engine": args.video_engine,
        "heygen_avatar_id": args.heygen_avatar_id,
        "replicate_used": False,
        "duration_sec": round(time.time() - started, 2),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    manifest = os.path.join(OUTPUT_DIR, "last_run.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("-" * 66)
    print(f"Готово за {result['duration_sec']} c")
    if video_path:
        print(f"Видео: {video_path}")
    print(f"Манифест: {manifest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AgnesError, tts_f5.F5Error, tts_local.TTSError, FileNotFoundError, RuntimeError) as exc:
        print(f"\nОШИБКА: {exc}", file=sys.stderr)
        raise SystemExit(1)
