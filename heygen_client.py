"""Клиент HeyGen AI v3 — говорящая голова с lip-sync по фото.

Контракт API (https://developers.heygen.com/reference/create-video):

  Загрузить фото:      POST {base}/assets           (multipart, type=image)
  Создать аватар:      POST {base}/avatars          (type=photo, file.asset_id)
  Статус аватара:      GET  {base}/avatars/{avatar_id}
  Создать видео:       POST {base}/videos            (type=avatar, avatar_id, audio/script, aspect_ratio)
  Статус видео:        GET  {base}/videos/{video_id}
  Скачать видео:       GET  video_url из ответа

Заголовок авторизации: X-API-KEY: <HEYGEN_API_KEY>

Важно: для генерации с нашим собственным аудио (F5-TTS) HeyGen требует
публично доступный URL аудиофайла. Локальный файл нужно раздать через
временный HTTP-сервер или загрузить в файловое хранилище.
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.heygen.com/v3"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class HeyGenError(RuntimeError):
    """Ошибка HeyGen API."""


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


class HeyGenClient:
    def __init__(self, api_key=None, base_url=None, max_attempts=6,
                 base_delay=2.0, timeout=120, dry_run=False):
        env = _load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
        self.api_key = api_key or os.environ.get("HEYGEN_API_KEY") or env.get("HEYGEN_API_KEY", "")
        base = base_url or os.environ.get("HEYGEN_BASE_URL") or env.get("HEYGEN_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = base.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.timeout = timeout
        self.dry_run = dry_run
        if not self.api_key and not dry_run:
            raise HeyGenError(
                "Не найден ключ HeyGen. Добавьте HEYGEN_API_KEY в .env "
                "(ключ — в личном кабинете heygen.com)."
            )

    # --- HTTP -------------------------------------------------------------
    def _backoff(self, attempt):
        import random
        return self.base_delay * (2 ** (attempt - 1)) * (1 + random.random() * 0.3)

    def _request(self, method, url, body=None, headers=None, expect="json"):
        """Выполнить HTTP-запрос с повторными попытками при ошибках."""
        h = {
            "User-Agent": USER_AGENT,
            "X-API-KEY": self.api_key,
        }
        if headers:
            h.update(headers)
        data = None
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = bytes(body)
                h["Content-Type"] = "application/octet-stream"
            elif isinstance(body, dict) and h.get("Content-Type", "").startswith("multipart/"):
                data, boundary = self._encode_multipart(body)
                h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            else:
                data = json.dumps(body).encode("utf-8")
                h["Content-Type"] = "application/json"

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            request = urllib.request.Request(url, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if expect == "bytes":
                        return raw
                    if not raw:
                        return {}
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        return {"_raw": raw.decode("utf-8", errors="replace")}
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in RETRY_STATUSES and attempt < self.max_attempts:
                    delay = self._backoff(attempt)
                    print(f"      HeyGen HTTP {exc.code}, повтор через {delay:.1f} c (попытка {attempt}/{self.max_attempts})")
                    time.sleep(delay)
                    continue
                body_txt = ""
                try:
                    body_txt = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                raise HeyGenError(
                    f"HeyGen API HTTP {exc.code}: {body_txt}"
                ) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    delay = self._backoff(attempt)
                    print(f"      HeyGen сетевая ошибка, повтор через {delay:.1f} c (попытка {attempt}/{self.max_attempts})")
                    time.sleep(delay)
                    continue
                raise HeyGenError(f"HeyGen сетевая ошибка: {exc}") from exc
        raise HeyGenError(f"HeyGen: попытки исчерпаны. Последняя ошибка: {last_error}")

    @staticmethod
    def _encode_multipart(fields):
        """fields: dict где значение — либо строка, либо кортеж (filename, bytes, content_type)."""
        boundary = "----HeyGenBoundary" + str(int(time.time() * 1000))
        parts = []
        for key, value in fields.items():
            parts.append(f"--{boundary}")
            if isinstance(value, tuple):
                filename, content, ctype = value
                parts.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"')
                parts.append(f"Content-Type: {ctype}")
                parts.append("")
                parts.append(content)
            else:
                parts.append(f'Content-Disposition: form-data; name="{key}"')
                parts.append("")
                parts.append(str(value))
        parts.append(f"--{boundary}--")
        parts.append("")
        body = "\r\n".join(parts).encode("utf-8")
        return body, boundary


    # --- Asset (загрузка изображения) -------------------------------------
    def upload_asset(self, file_path, asset_type="image"):
        """Загрузить локальный файл в HeyGen. Возвращает asset_id."""
        if self.dry_run:
            print("      DRY-RUN: загрузка ассета")
            return "asset_dry_run"
        if not os.path.exists(file_path):
            raise HeyGenError(f"нет файла: {file_path}")
        ctype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            content = f.read()
        filename = os.path.basename(file_path)
        body = {
            "type": asset_type,
            "file": (filename, content, ctype),
        }
        resp = self._request("POST", f"{self.base_url}/assets", body=body,
                             headers={"Content-Type": "multipart/form-data"})
        asset_id = resp.get("data", {}).get("asset_id") or resp.get("asset_id")
        if not asset_id:
            raise HeyGenError(f"в ответе нет asset_id: {json.dumps(resp)[:300]}")
        print(f"      HeyGen: ассет загружен, asset_id={asset_id}")
        return asset_id

    # --- Avatar (фото-аватар) ---------------------------------------------
    def create_avatar(self, asset_id, name="Doctor Avatar"):
        """Создать фото-аватар из загруженного ассета. Возвращает avatar_id."""
        if self.dry_run:
            print("      DRY-RUN: создание аватара")
            return "avatar_dry_run"
        body = {
            "type": "photo",
            "name": name,
            "file": {"type": "asset_id", "asset_id": asset_id},
        }
        resp = self._request("POST", f"{self.base_url}/avatars", body=body)
        avatar_id = resp.get("data", {}).get("avatar_item", {}).get("id") or resp.get("avatar_id")
        if not avatar_id:
            raise HeyGenError(f"в ответе нет avatar_id: {json.dumps(resp)[:300]}")
        print(f"      HeyGen: аватар создаётся, avatar_id={avatar_id}")
        return avatar_id

    def wait_avatar(self, avatar_id, poll_interval=5.0, max_wait=600):
        """Дождаться готовности аватара (status == completed)."""
        if self.dry_run:
            print("      DRY-RUN: аватар готов")
            return {"status": "completed"}
        deadline = time.time() + max_wait
        started = time.time()
        while True:
            resp = self._request("GET", f"{self.base_url}/avatars/{avatar_id}")
            data = resp.get("data", resp)
            status = data.get("status")
            if status == "completed":
                print(f"      HeyGen: аватар готов за {time.time() - started:.0f} c")
                return data
            if status in ("failed", "error"):
                raise HeyGenError(f"HeyGen аватар {avatar_id} не готов: status={status}")
            if time.time() > deadline:
                raise HeyGenError(f"HeyGen: таймаут ожидания аватара {max_wait} c")
            print(f"      HeyGen: аватар в обработке ({status})…")
            time.sleep(poll_interval)


    # --- Video ------------------------------------------------------------
    def create_video(self, avatar_id, audio_url=None, script=None,
                     voice_id=None, aspect_ratio="9:16",
                     video_name=None):
        """Создать задачу генерации видео. Возвращает video_id."""
        if self.dry_run:
            print("      DRY-RUN: создание видео")
            return "video_dry_run"
        if not audio_url and not script:
            raise HeyGenError("нужен либо audio_url, либо script (текст)")
        body = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "aspect_ratio": aspect_ratio,
        }
        if video_name:
            body["video_name"] = video_name
        if audio_url:
            body["audio"] = {"url": audio_url}
        if script:
            body["script"] = script
            if voice_id:
                body["voice_id"] = voice_id
        resp = self._request("POST", f"{self.base_url}/videos", body=body)
        video_id = resp.get("data", {}).get("video_id") or resp.get("video_id")
        if not video_id:
            raise HeyGenError(f"в ответе нет video_id: {json.dumps(resp)[:300]}")
        print(f"      HeyGen: задача видео создана, video_id={video_id}")
        return video_id

    def wait_video(self, video_id, poll_interval=5.0, max_wait=900):
        """Дождаться готовности видео (status == completed). Возвращает video_url."""
        if self.dry_run:
            print("      DRY-RUN: видео готово")
            return "https://example.com/dry_run.mp4"
        deadline = time.time() + max_wait
        started = time.time()
        last_status = None
        while True:
            resp = self._request("GET", f"{self.base_url}/videos/{video_id}")
            data = resp.get("data", resp)
            status = data.get("status")
            if status != last_status:
                print(f"      HeyGen: видео {status} ({time.time() - started:.0f} c)")
                last_status = status
            if status == "completed":
                video_url = data.get("video_url") or (data.get("url"))
                if not video_url:
                    raise HeyGenError(f"видео готово, но нет video_url: {json.dumps(data)[:300]}")
                print(f"      HeyGen: видео готово за {time.time() - started:.0f} c")
                return video_url
            if status in ("failed", "error", "cancelled"):
                err = data.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise HeyGenError(f"HeyGen видео {video_id} провалилось: {msg or 'без описания'}")
            if time.time() > deadline:
                raise HeyGenError(f"HeyGen: таймаут ожидания видео {max_wait} c")
            time.sleep(poll_interval)

    def download(self, url, dest):
        """Скачать готовое видео по URL."""
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        payload = self._request("GET", url, expect="bytes")
        with open(dest, "wb") as f:
            f.write(payload)
        return dest

    def generate(self, avatar_id, out_path, audio_url=None, script=None,
                 voice_id=None, aspect_ratio="9:16",
                 poll_interval=5.0, max_wait=900, **kwargs):
        """Полный цикл: создать задачу → дождаться → скачать. Возвращает путь к mp4."""
        video_id = self.create_video(
            avatar_id=avatar_id, audio_url=audio_url, script=script,
            voice_id=voice_id, aspect_ratio=aspect_ratio,
            video_name=kwargs.get("video_name"),
        )
        if video_id == "video_dry_run":
            return None
        video_url = self.wait_video(video_id, poll_interval=poll_interval, max_wait=max_wait)
        return self.download(video_url, out_path)