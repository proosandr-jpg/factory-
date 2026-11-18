"""Клиент Replicate API на стандартной библиотеке (без requests).

Зачем свой клиент: в окружении нет requests/httpx, а тянуть зависимости ради
четырёх HTTP-запросов не нужно. Здесь есть всё, что требует пайплайн:
загрузка файлов, запуск модели по версии, опрос статуса, скачивание результата.

Важная деталь: api.replicate.com стоит за Cloudflare, который отдаёт
403 (error 1010) на дефолтный User-Agent urllib. Поэтому браузерный UA
подставляется в каждый запрос — без него любые вызовы падают.
"""

import json
import mimetypes
import os
import random
import time
import urllib.error
import urllib.request
import uuid

API_BASE = "https://api.replicate.com/v1"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Коды, при которых имеет смысл повторить запрос (перегрузка Replicate, сеть).
RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}


class ReplicateError(RuntimeError):
    """Ошибка API Replicate с сохранённым телом ответа."""


class PredictionFailed(ReplicateError):
    """Модель вернула status=failed."""


def load_env(path=".env"):
    """Простой парсер .env: KEY=VALUE, комментарии через #, кавычки не обязательны."""
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


def get_token(env=None):
    """Токен: сначала переменная окружения (сервер), потом .env (локально)."""
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        token = load_env().get("REPLICATE_API_TOKEN", "")
    if not token:
        raise ReplicateError(
            "Не найден REPLICATE_API_TOKEN. Положите его в .env или в переменные окружения."
        )
    return token


class ReplicateClient:
    def __init__(self, token=None, max_attempts=6, base_delay=2.0, timeout=120):
        self.token = token or get_token()
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.timeout = timeout
        self._versions = {}

    # --- низкий уровень -------------------------------------------------
    def _request(self, method, url, body=None, content_type=None, expect="json"):
        """HTTP-запрос с экспоненциальным повтором и уважением к Retry-After."""
        data = body
        headers = {
            "Authorization": "Bearer " + self.token,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type

        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    if expect == "bytes":
                        return payload
                    if not payload:
                        return {}
                    return json.loads(payload.decode("utf-8"))

            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", "replace")
                last_error = ReplicateError(
                    f"{method} {url} -> HTTP {exc.code}: {err_body[:500]}"
                )
                retryable = exc.code in RETRY_STATUSES
                if not retryable or attempt == self.max_attempts:
                    raise last_error from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after or "").isdigit() else self._backoff(attempt)

            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = ReplicateError(f"{method} {url} -> сетевая ошибка: {exc}")
                if attempt == self.max_attempts:
                    raise last_error from exc
                delay = self._backoff(attempt)

            print(f"      повтор {attempt}/{self.max_attempts - 1} через {delay:.1f} c "
                  f"({last_error})")
            time.sleep(delay)

        raise last_error or ReplicateError("запрос не выполнен")

    def _backoff(self, attempt):
        """1.5, 3, 6, 12... секунд плюс джиттер, чтобы не бить в API синхронно."""
        return self.base_delay * (2 ** (attempt - 1)) * (1 + random.random() * 0.3)

    def _url(self, path):
        return path if path.startswith("http") else API_BASE + path

    # --- операции -------------------------------------------------------
    def upload(self, path):
        """Загрузить файл, вернуть публичный URL для входа модели."""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise ReplicateError(f"файл не найден: {path}")
        with open(path, "rb") as f:
            content = f.read()

        boundary = "----factory" + uuid.uuid4().hex
        filename = os.path.basename(path)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts = [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="content"; filename="{filename}"'.encode(),
            f"Content-Type: {mime}".encode(),
            b"",
            content,
            f"--{boundary}--".encode(),
            b"",
        ]
        body = b"\r\n".join(parts)

        data = self._request(
            "POST",
            self._url("/files"),
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        urls = data.get("urls") or {}
        url = urls.get("get") or data.get("url")
        if not url:
            raise ReplicateError(f"Replicate не вернул URL файла: {json.dumps(data)[:300]}")
        return url

    def version_of(self, model):
        """Актуальная версия модели (кэшируется на время прогона)."""
        if model in self._versions:
            return self._versions[model]
        data = self._request("GET", self._url(f"/models/{model}"))
        version = (data.get("latest_version") or {}).get("id")
        if not version:
            raise ReplicateError(f"у модели {model} нет latest_version")
        self._versions[model] = version
        return version

    def run(self, model, inputs, poll_interval=3.0, max_wait=900, label=None):
        """Запустить модель и дождаться результата. Возвращает URL результата."""
        label = label or model
        version = self.version_of(model)

        print(f"      {label}: запуск ({model})")
        prediction = self._request(
            "POST",
            self._url("/predictions"),
            body=json.dumps({"version": version, "input": inputs}).encode(),
            content_type="application/json",
        )
        pred_id = prediction.get("id")
        if not pred_id:
            raise ReplicateError(f"нет id прогноза: {json.dumps(prediction)[:300]}")

        started = time.time()
        deadline = started + max_wait
        status = prediction.get("status")
        last_status = None

        while status in ("starting", "processing", None):
            if time.time() > deadline:
                raise ReplicateError(
                    f"{label}: не дождались результата за {max_wait} c "
                    f"(status={status}, id={pred_id})"
                )
            if status != last_status:
                print(f"      {label}: {status}…")
                last_status = status
            time.sleep(poll_interval)
            prediction = self._request("GET", self._url(f"/predictions/{pred_id}"))
            status = prediction.get("status")

        if status != "succeeded":
            raise PredictionFailed(
                f"{label}: status={status}, error={prediction.get('error')}"
            )

        output = prediction.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if not output:
            raise ReplicateError(f"{label}: пустой output")
        print(f"      {label}: готово за {time.time() - started:.1f} c")
        return output

    def download(self, url, dest):
        """Скачать результат на диск с повтором при обрыве."""
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        payload = self._request("GET", url, expect="bytes")
        with open(dest, "wb") as f:
            f.write(payload)
        return dest
