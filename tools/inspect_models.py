"""Служебный скрипт: показать версию и входную схему моделей Replicate.

Нужен, чтобы не угадывать имена полей. Запуск: python tools/inspect_models.py
Секреты не печатаются.
"""

import json
import os
import sys
import urllib.request

MODELS = [
    "resemble-ai/chatterbox-multilingual",
    "bytedance/omni-human",
]


def load_env(path=".env"):
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


def api(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main():
    token = os.environ.get("REPLICATE_API_TOKEN") or load_env().get("REPLICATE_API_TOKEN")
    if not token:
        print("Нет REPLICATE_API_TOKEN")
        return 1

    for model in MODELS:
        print("=" * 70)
        print(model)
        try:
            data = api(f"https://api.replicate.com/v1/models/{model}", token)
        except Exception as exc:  # noqa: BLE001 - диагностика
            print(f"  ОШИБКА запроса: {type(exc).__name__}: {exc}")
            continue

        latest = data.get("latest_version") or {}
        print(f"  version: {latest.get('id')}")
        print(f"  runs:    {data.get('run_count')}")

        schema = (latest.get("openapi_schema") or {}).get("components", {}).get("schemas", {})
        input_schema = schema.get("Input", {})
        props = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        print(f"  required: {required}")
        for name, spec in props.items():
            kind = spec.get("type") or spec.get("allOf") or spec.get("anyOf")
            default = spec.get("default", "—")
            print(f"    - {name}: {kind} | default={default} | {str(spec.get('description', ''))[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
