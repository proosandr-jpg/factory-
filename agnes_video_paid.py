"""Клиент Agnes Video 2.5 (модель `agnes-video-2.5`), только стандартная библиотека.

Контракт из официальной документации https://wiki.agnes-ai.com/en/docs/agnes-video-25:

  Создать задачу:  POST {base}/videos          (base = https://apihub.agnes-ai.com/v1)
  Опрос статуса:   GET  https://apihub.agnes-ai.com/agnesapi?video_id=...&model_name=agnes-video-2.5
  Результат:       status == "completed", ссылка в поле url

Режимы (mode):
  text       — только промпт;
  keyframe   — управление первым/последним кадром (first_frame / last_frame);
  reference  — референсы images / audios / videos.

Важно: это генеративная видеомодель, а не липсинк. Она делает сцену по описанию,
но не синхронизирует губы под нашу озвучку — для говорящей головы остаётся omni-human.
"""

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
MODEL_ID = "agnes-video-2.5"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}

# Цены из документации, $ за секунду видео.
PRICE_PER_SECOND = {"720P": 0.025, "1080P": 0.040, "1K": 0.040, "2K": 0.055}

MODES = {"text", "keyframe", "reference"}
SIZES = {"720P", "1080P", "1K", "2K"}


class AgnesError(RuntimeError):
    """Ошибка Agnes API."""


def _load_env(path=".env"):
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


class AgnesVideoClient:
    def __init__(self, api_key=None, base_url=None, max_attempts=6,
                 base_delay=2.0, timeout=120, dry_run=False):
        env = _load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
        self.api_key = api_key or os.environ.get("AGNES_API_KEY") or env.get("AGNES_API_KEY", "")
        base = base_url or os.environ.get("AGNES_BASE_URL") or env.get("AGNES_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = base.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.timeout = timeout
        self.dry_run = dry_run
        if not self.api_key and not dry_run:
            raise AgnesError(
                "Не найден ключ Agnes. Добавьте AGNES_API_KEY в .env (ключ — в личном кабинете agnes-ai.com)."
            )

    # --- HTTP -------------------------------------------------------------
    def _backoff(self, attempt):
        return self.base_delay * (2 ** (attempt - 1)) * (1 + random.random() * 0.3)

    def _request(self, method, url, body=None, expect="json"):
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    if expect == "bytes":
                        return payload
                    return json.loads(payload.decode("utf-8")) if payload else {}

            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")
                if exc.code == 401:
                    raise AgnesError(
                        "Agnes отклонил ключ (HTTP 401). Проверьте значение в .env."
                    ) from exc
                if exc.code == 402:
                    raise AgnesError(
                        "На аккаунте Agnes закончились средства (HTTP 402). Пополните баланс."
                    ) from exc
                if exc.code == 400:
                    raise AgnesError(f"Agnes отклонил запрос (HTTP 400): {text[:600]}") from exc

                last_error = AgnesError(f"{method} {url} -> HTTP {exc.code}: {text[:400]}")
                if exc.code not in RETRY_STATUSES or attempt == self.max_attempts:
                    raise last_error from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after or "").isdigit() else self._backoff(attempt)

            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = AgnesError(f"{method} {url} -> сетевая ошибка: {exc}")
                if attempt == self.max_attempts:
                    raise last_error from exc
                delay = self._backoff(attempt)

            print(f"      повтор {attempt}/{self.max_attempts - 1} через {delay:.1f} c ({last_error})")
            time.sleep(delay)

        raise last_error or AgnesError("запрос не выполнен")

    # --- API --------------------------------------------------------------
    @property
    def create_url(self):
        return f"{self.base_url}/videos"

    @property
    def poll_url(self):
        # Эндпоинт опроса живёт на корне хоста, без сегмента /v1.
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        return f"{root}/agnesapi"

    def create_task(self, prompt, mode="text", seconds="5", size="720P",
                    aspect_ratio="9:16", first_frame=None, last_frame=None,
                    images=None, audios=None, videos=None, seed=None):
        """Создать задачу генерации. Возвращает ответ API (там есть video_id)."""
        if not prompt or not prompt.strip():
            raise AgnesError("Промпт пустой.")
        if mode not in MODES:
            raise AgnesError(f"mode={mode!r}, допустимо: {sorted(MODES)}")
        if size not in SIZES:
            raise AgnesError(f"size={size!r}, допустимо: {sorted(SIZES)}")
        if not 4 <= int(seconds) <= 12:
            raise AgnesError("seconds должен быть в диапазоне 4–12")

        body = {
            "model": MODEL_ID,
            "prompt": prompt.strip(),
            "mode": mode,
            "seconds": str(int(seconds)),
            "size": size,
            "aspect_ratio": aspect_ratio,
        }
        if seed is not None:
            body["seed"] = int(seed)
        if first_frame:
            body["first_frame"] = first_frame
        if last_frame:
            body["last_frame"] = last_frame
        if images:
            body["images"] = images
        if audios:
            body["audios"] = audios
        if videos:
            body["videos"] = videos

        # Правила режимов из документации.
        if mode == "text" and any((first_frame, last_frame, images, audios, videos)):
            raise AgnesError("mode=text не принимает медиа")
        if mode == "keyframe" and not (first_frame or last_frame):
            raise AgnesError("mode=keyframe требует first_frame или last_frame")
        if mode == "keyframe" and any((images, audios, videos)):
            raise AgnesError("mode=keyframe не принимает images/audios/videos")
        if mode == "reference" and any((first_frame, last_frame)):
            raise AgnesError("mode=reference не принимает first_frame/last_frame")
        if mode == "reference" and not any((images, audios, videos)):
            raise AgnesError("mode=reference требует хотя бы один референс")

        if self.dry_run:
            print("      DRY-RUN, тело запроса:")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:1200])
            return {"video_id": "dry_run", "status": "queued", "dry_run": True}

        return self._request("POST", self.create_url, body=body)

    def wait(self, video_id, poll_interval=2.0, max_wait=1800, label="Agnes"):
        """Опрашивать задачу до completed/failed. Возвращает финальный ответ."""
        deadline = time.time() + max_wait
        started = time.time()
        last_progress = None
        while True:
            query = urllib.parse.urlencode({"video_id": video_id, "model_name": MODEL_ID})
            data = self._request("GET", f"{self.poll_url}?{query}")
            status = data.get("status")
            progress = data.get("progress")
            if progress != last_progress:
                print(f"      {label}: {status}, {progress}%")
                last_progress = progress
            if status == "completed":
                print(f"      {label}: готово за {time.time() - started:.1f} c")
                return data
            if status == "failed":
                error = data.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise AgnesError(f"{label}: задача провалилась — {message or 'без описания'}")
            if time.time() > deadline:
                raise AgnesError(f"{label}: таймаут {max_wait} c (video_id={video_id}, status={status})")
            time.sleep(poll_interval)

    def generate(self, prompt, out_path, **kwargs):
        """Создать задачу, дождаться и скачать mp4. Возвращает путь к файлу."""
        max_wait = kwargs.pop("max_wait", 1800)
        poll_interval = kwargs.pop("poll_interval", 2.0)
        task = self.create_task(prompt, **kwargs)
        if task.get("dry_run"):
            return None
        video_id = task.get("video_id") or task.get("id")
        if not video_id:
            raise AgnesError(f"в ответе нет video_id: {json.dumps(task)[:300]}")
        print(f"      Agnes: задача {video_id} ({kwargs.get('size', '720P')}, "
              f"{kwargs.get('seconds', '5')} c, ~${estimate_cost(kwargs.get('size', '720P'), kwargs.get('seconds', '5')):.3f})")

        final = self.wait(video_id, poll_interval=poll_interval, max_wait=max_wait)
        url = final.get("url")
        if not url:
            raise AgnesError("задача завершена, но в ответе нет url")
        return self.download(url, out_path)

    def download(self, url, dest):
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        payload = self._request("GET", url, expect="bytes")
        with open(dest, "wb") as f:
            f.write(payload)
        return dest


def estimate_cost(size, seconds):
    """Оценка стоимости по тарифу из документации, $."""
    return PRICE_PER_SECOND.get(size, 0.025) * float(seconds)
