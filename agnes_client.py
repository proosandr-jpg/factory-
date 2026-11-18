"""Клиент для генерации мультяшных изображений через Agnes API.

Поддерживает:
- Генерацию по текстовому промпту с эталонным фото (extra_body.image)
- Retry-логику с exponential backoff для нестабильного шлюза Agnes
- Размер size="2K", ratio="9:16" по умолчанию
- response_format внутри extra_body
"""

import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

logger = logging.getLogger(__name__)

# Коды ответов, при которых нужно повторить запрос
RETRYABLE_STATUS_CODES = {401, 429, 500, 502, 503, 504}

# Параметры retry
MAX_RETRIES = 5
INITIAL_BACKOFF = 2  # секунд


class AgnesClient:
    """Клиент для работы с Agnes API (генерация изображений).

    Поддерживает генерацию мультяшных изображений по текстовому
    описанию с опциональным эталонным фото.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Инициализирует клиент.

        Args:
            api_key: Ключ API. Если не передан, берётся из env ``AGNES_API_KEY``.
            base_url: Базовый URL API. Если не передан, берётся из env ``AGNES_BASE_URL``.
        """
        self.api_key = api_key or os.getenv("AGNES_API_KEY")
        self.base_url = (base_url or os.getenv("AGNES_BASE_URL", "")).rstrip("/")

        if not self.api_key:
            raise ValueError(
                "API-ключ не найден. Установите переменную AGNES_API_KEY в .env "
                "или передайте api_key."
            )
        if not self.base_url:
            raise ValueError(
                "Базовый URL не найден. Установите переменную AGNES_BASE_URL в .env "
                "или передайте base_url."
            )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

        # Атрибуты для отслеживания последнего запроса
        self.last_status_code: Optional[int] = None
        self.last_attempt_count: int = 0

    @property
    def _endpoint(self) -> str:
        """Полный URL эндпоинта генерации изображений."""
        return f"{self.base_url}/v1/images/generations"

    @staticmethod
    def _encode_image(image_path: str) -> str:
        """Кодирует изображение в base64.

        Args:
            image_path: Путь к файлу изображения.

        Returns:
            Base64-строка изображения.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Эталонное изображение не найдено: {image_path}"
            )

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _post_with_retry(self, body: dict) -> Tuple[dict, int]:
        """Отправляет POST-запрос с логикой повторных попыток (exponential backoff).

        Повторяет запрос при кодах 401, 429, 500, 502, 503, 504.
        Начальная пауза — 2 секунды, каждая следующая умножается на 2.
        Максимум 5 попыток.

        Args:
            body: Тело запроса в виде словаря.

        Returns:
            Кортеж (результат ответа в виде dict, код статуса).

        Raises:
            requests.HTTPError: Если все попытки провалились.
        """
        last_status_code: Optional[int] = None
        response: Optional[requests.Response] = None

        for attempt in range(1, MAX_RETRIES + 1):
            response = self._session.post(self._endpoint, json=body)
            last_status_code = response.status_code
            self.last_status_code = response.status_code
            self.last_attempt_count = attempt

            if response.status_code == 200:
                logger.info(
                    "Попытка %d: успех (код %d)", attempt, response.status_code
                )
                return response.json(), response.status_code

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    logger.warning(
                        "Попытка %d/%d: код ответа %d, пауза %.1f сек "
                        "до следующей попытки",
                        attempt,
                        MAX_RETRIES,
                        response.status_code,
                        backoff,
                    )
                    print(
                        f"  Попытка {attempt}/{MAX_RETRIES}: код {response.status_code}, "
                        f"пауза {backoff:.0f} сек..."
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Попытка %d/%d: код ответа %d — все попытки исчерпаны",
                        attempt,
                        MAX_RETRIES,
                        response.status_code,
                    )
                    print(
                        f"  Попытка {attempt}/{MAX_RETRIES}: код {response.status_code} "
                        f"— все попытки исчерпаны"
                    )
            else:
                # Не retryable ошибка — сразу выбрасываем
                logger.error(
                    "Попытка %d: необрабатываемый код ответа %d",
                    attempt,
                    response.status_code,
                )
                response.raise_for_status()

        # Все попытки провалились
        raise requests.HTTPError(
            f"Все {MAX_RETRIES} попытки исчерпаны. "
            f"Последний код ответа: {last_status_code}",
            response=response,
        )

    def generate(
        self,
        prompt: str,
        reference_image_path: Optional[str] = None,
        size: str = "2K",
        ratio: str = "9:16",
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        response_format: str = "b64_json",
        **extra_kwargs,
    ) -> Tuple[dict, int]:
        """Генерирует изображение по текстовому описанию.

        Args:
            prompt: Текстовое описание (промпт) для генерации.
            reference_image_path: Путь к эталонному фото. Если передан,
                изображение кодируется в base64 и отправляется в
                ``extra_body.image``.
            size: Размер изображения (по умолчанию "2K").
            ratio: Соотношение сторон (по умолчанию "9:16").
            num_inference_steps: Количество шагов инференса.
            guidance_scale: Масштаб направления.
            response_format: Формат ответа (передаётся строго внутри
                ``extra_body``, не на верхнем уровне).
            **extra_kwargs: Дополнительные параметры, передаваемые в тело
                запроса.

        Returns:
            Кортеж (ответ API в виде dict, код статуса HTTP).

        Raises:
            requests.HTTPError: При ошибке HTTP-запроса после всех попыток.
            ValueError: Если параметры некорректны.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Промпт не может быть пустым.")

        body: dict = {
            "prompt": prompt,
            "size": size,
            "ratio": ratio,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
        }

        # extra_body: response_format и эталонное изображение
        extra_body: dict = {
            "response_format": response_format,
        }

        if reference_image_path:
            image_b64 = self._encode_image(reference_image_path)
            extra_body["image"] = image_b64

        body["extra_body"] = extra_body

        # Добавляем любые дополнительные параметры
        body.update(extra_kwargs)

        return self._post_with_retry(body)

    def generate_and_save(
        self,
        prompt: str,
        reference_image_path: Optional[str] = None,
        output_path: Optional[str] = None,
        **kwargs,
    ) -> Tuple[str, int]:
        """Генерирует изображение и сохраняет его на диск.

        Args:
            prompt: Текстовое описание.
            reference_image_path: Путь к эталонному фото.
            output_path: Путь для сохранения результата. Если не указан,
                формируется автоматически.
            **kwargs: Дополнительные параметры для :meth:`generate`.

        Returns:
            Кортеж (путь к сохранённому файлу, код статуса HTTP).
        """
        result, status_code = self.generate(
            prompt, reference_image_path, **kwargs
        )

        # Определяем, где лежит изображение в ответе
        image_data = result.get("image") or result.get("images", [None])[0]

        if image_data is None:
            raise ValueError("Ответ API не содержит данных изображения.")

        # Если это base64-строка — декодируем
        if isinstance(image_data, str):
            image_bytes = base64.b64decode(image_data)
        elif isinstance(image_data, dict):
            # Иногда API возвращает {"url": "..."} или {"base64": "..."}
            if "url" in image_data:
                image_bytes = requests.get(image_data["url"]).content
            elif "base64" in image_data:
                image_bytes = base64.b64decode(image_data["base64"])
            else:
                raise ValueError(
                    f"Не удалось извлечь изображение из ответа: {image_data}"
                )
        else:
            raise ValueError(
                f"Неподдерживаемый формат данных изображения: "
                f"{type(image_data)}"
            )

        if output_path is None:
            output_path = f"generated_{os.urandom(4).hex()}.png"

        with open(output_path, "wb") as f:
            f.write(image_bytes)

        return output_path, status_code

    def generate_character_sheet(
        self,
        reference_image_path: str,
        output_path: str,
    ) -> Tuple[str, int]:
        """Генерирует персонажный лист мультяшного врача по фото реального человека.

        Преобразует фото реального человека в дружелюбного мультяшного
        врача в белом медицинском халате с стетоскопом.

        Args:
            reference_image_path: Путь к фото реального человека.
            output_path: Путь для сохранения результата.

        Returns:
            Кортеж (путь к сохранённому файлу, код статуса HTTP).
        """
        prompt = (
            "Transform this photo into a friendly cartoon-style medical doctor "
            "character. Preserve the person's facial features, hairstyle, and "
            "overall likeness. Clean white medical coat, stethoscope around neck, "
            "neutral light background. Flat 2D vector illustration style, soft "
            "colors, professional but approachable. Character reference sheet with "
            "front view, three-quarter view, and profile view in a single image."
        )

        return self.generate_and_save(
            prompt=prompt,
            reference_image_path=reference_image_path,
            output_path=output_path,
        )