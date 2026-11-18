"""Клиент Agnes Video 2.5 Flash с политикой ожидания при перегрузке очереди.

Зачем отдельный модуль: базовый ``agnes_video_paid.py`` умеет только модель
``agnes-video-2.5`` (платную). Free-вариант — это та же схема запроса
(``mode`` / ``seconds`` / ``size`` / ``aspect_ratio``), но:

  * model = ``agnes-video-2.5-flash``;
  * ``size`` строго ``720P``, иначе HTTP 400 «size must be 720P»;
  * опрос задачи требует ``model_name=agnes-video-2.5-flash``.

Плюс своя политика повторов: Agnes при перегрузке отвечает HTTP 503
``video_queue_full``, и ждать секунду-две бессмысленно.

    30 c -> 60 c -> 120 c -> 120 c, всего 5 попыток.
"""

import json
import time
import urllib.parse

from agnes_video_paid import AgnesError, AgnesVideoClient

MODEL_FLASH = "agnes-video-2.5-flash"
MODEL_V20 = "agnes-video-v2.0"
MODEL_PAID = "agnes-video-2.5"

# Что известно про модели на 01.11.2026 (проверено живыми запросами).
VIDEO_MODELS = {
    MODEL_FLASH: {
        "sizes": ["720P"],
        "price_per_second": 0.0,
        "notes": "триальный тариф $0/с; при перегрузке отвечает 503 video_queue_full",
    },
    MODEL_PAID: {
        "sizes": ["720P", "1080P", "1K", "2K"],
        "price_per_second": 0.025,
        "notes": "платная; на аккаунте отвечает 403 insufficient_user_quota",
    },
    MODEL_V20: {
        "sizes": [],
        "price_per_second": 0.0,
        "notes": "канал отключён: 500 get_channel_failed",
    },
}

QUEUE_DELAYS = (30, 60, 120, 120)
MAX_ATTEMPTS = 5


def estimate_cost(seconds=5, model=MODEL_FLASH, size="720P"):
    profile = VIDEO_MODELS.get(model, {})
    return profile.get("price_per_second", 0.0) * float(seconds)


class FlashQueueClient(AgnesVideoClient):
    """Agnes Video 2.5 Flash: 720P, повторы 30/60/120/120 при 503."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("model", None)
        super().__init__(*args, **kwargs)
        # Короткие внутренние повторы отключаем: расписанием управляет обёртка.
        self.max_attempts = 1

    # --- повторы ---------------------------------------------------------
    def _request(self, method, url, body=None, expect="json"):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return super()._request(method, url, body=body, expect=expect)
            except AgnesError as exc:
                message = str(exc)
                is_queue = "HTTP 503" in message or "video_queue_full" in message
                if not is_queue:
                    raise
                if attempt == MAX_ATTEMPTS:
                    raise AgnesError(
                        f"Agnes перегружен: очередь не приняла задачу после {MAX_ATTEMPTS} попыток.\n"
                        f"Последний ответ API: {message[:200]}\n"
                        "Подождите час или попробуйте в другое время суток."
                    ) from exc
                delay = QUEUE_DELAYS[min(attempt - 1, len(QUEUE_DELAYS) - 1)]
                print(f"      Agnes перегружен, пауза {delay} c "
                      f"(попытка {attempt}/{MAX_ATTEMPTS})")
                time.sleep(delay)
        raise AgnesError("Agnes: попытки исчерпаны")

    # --- задача ----------------------------------------------------------
    def create_task(self, prompt, mode="text", seconds="5", size="720P",
                    aspect_ratio="9:16", seed=None, **kwargs):
        if not prompt or not prompt.strip():
            raise AgnesError("Промпт пустой.")
        if mode != "text":
            raise AgnesError(f"Flash-обёртка поддерживает только mode=text, получено {mode!r}")
        if size != "720P":
            raise AgnesError("agnes-video-2.5-flash принимает только size=720P")
        if not 4 <= int(seconds) <= 12:
            raise AgnesError("seconds должен быть в диапазоне 4–12")

        body = {
            "model": MODEL_FLASH,
            "prompt": prompt.strip(),
            "mode": "text",
            "seconds": str(int(seconds)),
            "size": "720P",
            "aspect_ratio": aspect_ratio,
        }
        if seed is not None:
            body["seed"] = int(seed)

        if self.dry_run:
            print("      DRY-RUN, тело запроса:")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:1200])
            return {"video_id": "dry_run", "status": "queued", "dry_run": True}

        return self._request("POST", self.create_url, body=body)

    # --- ожидание --------------------------------------------------------
    def wait(self, video_id, poll_interval=2.0, max_wait=1800, label="Agnes", model=None):
        deadline = time.time() + max_wait
        started = time.time()
        last_progress = None

        while True:
            query = urllib.parse.urlencode({"video_id": video_id, "model_name": MODEL_FLASH})
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
                raise AgnesError(
                    f"{label}: таймаут {max_wait} c (video_id={video_id}, status={status})"
                )
            time.sleep(poll_interval)

    def generate(self, prompt, out_path, max_wait=1800, poll_interval=2.0, **kwargs):
        """Создать задачу, дождаться, скачать. Возвращает путь к mp4."""
        seconds = kwargs.get("seconds", 5)
        task = self.create_task(prompt, **kwargs)
        if task.get("dry_run"):
            return None
        video_id = task.get("video_id") or task.get("id")
        if not video_id:
            raise AgnesError(f"в ответе нет video_id: {json.dumps(task)[:300]}")

        print(f"      Agnes: задача {video_id} ({MODEL_FLASH}, "
              f"~${estimate_cost(seconds):.3f} по триальному тарифу)")

        final = self.wait(video_id, poll_interval=poll_interval, max_wait=max_wait)
        url = final.get("url") or (final.get("metadata") or {}).get("url")
        if not url:
            raise AgnesError("задача завершена, но URL видео не найден в ответе")
        return self.download(url, out_path)
