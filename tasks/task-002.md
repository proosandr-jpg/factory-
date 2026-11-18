# Задача task-002: HeyGen — отладка генерации видео на сервере

## Описание
На сервере 178.172.137.203 (Ubuntu 24.04) настроен nginx, аудио-файл скопирован в `/var/www/html/audio/voice_nose.wav`. Нужно:
1. Скопировать файлы фабрики (включая `heygen_client.py`, обновлённый `pipeline.py`) на сервер.
2. Добавить `HEYGEN_API_KEY` в `.env` на сервере.
3. Проверить доступность аудио по HTTP (`curl -I http://178.172.137.203/audio/voice_nose.wav`).
4. Запустить генерацию видео через HeyGen: `python3 pipeline.py --video-engine heygen --heygen-audio-url http://178.172.137.203/audio/voice_nose.wav --text-file scenarios/01-bez-pokazaniy.txt`.
5. При необходимости создать фото-аватар HeyGen из `assets/avatar.png`.
6. Сохранить готовое MP4 в `output/video/` на сервере.

## Границы (что можно трогать)
**Можно:**
- `pipeline.py` (только HeyGen-специфичные изменения)
- `heygen_client.py`
- `.env` (добавить HEYGEN_API_KEY — не коммитить!)
- `output/` на сервере
- Любые файлы в worktree `agent-server/`

**Нельзя:**
- Модифицировать `COORDINATION.md` (кроме обновления статуса этой задачи).
- Модифицировать `tasks/` (кроме обновления статуса этой задачи).
- Коммитить `.env` с реальными ключами в git.

## Критерии приёмки
- [ ] На сервере запущена команда `pipeline.py --video-engine heygen ...`.
- [ ] HeyGen создал фото-аватар из `assets/avatar.png` (или использован существующий avatar_id).
- [ ] Видео сгенерировано со статусом `completed` и скачано на сервер.
- [ ] Готовый MP4 лежит в `output/video/` на сервере.
- [ ] Лог успешного прогона сохранён (например, в `output/last_run.json`).
- [ ] Изменения закоммичены в ветку `agent/server` и запушены в origin.
- [ ] `COORDINATION.md` обновлён: статус task-002 → `завершено`.

## Ответственный
`agent-server`

## Статус
в работе (зависимость task-001 устранена, аватар доступен по URL)

## Аватар для HeyGen
- URL: `https://qazimir.by/media/avatar.png` (image/png, 200 OK)
- Локальный путь на сервере: `/var/www/qazimir-media/avatar.png`
- Можно загружать через `heygen_client.upload_asset()` с этого локального пути, либо передавать URL при создании ассета.
- Готовый `avatar_id` HeyGen пока не получен.