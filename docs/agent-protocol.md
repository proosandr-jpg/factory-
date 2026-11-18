# Протокол координации агентов — инструкция для agent-server и agent-git

## Обзор
Проект "Фабрика контента" координирует трёх агентов через Git:
1. `agent-local` (Windows, локально) — инициатор, создаёт структуру, багфиксы, новые фичи.
2. `agent-server` (Ubuntu 178.172.137.203) — запуск pipeline на сервере, HeyGen, nginx.
3. `agent-git` (Git-репозиторий) — ревью, защита main, мержи.

Вся координация ведётся через файлы в репозитории:
- `COORDINATION.md` — доска задач (кто, что, какой статус).
- `tasks/task-*.md` — детальное описание каждой задачи.
- `docs/agent-protocol.md` — эта инструкция.

## Шаг 0: Подготовка (выполняется один раз)

### Для agent-server (на Ubuntu 178.172.137.203)
```bash
# 1. Клонировать репозиторий
git clone https://github.com/proosandr-jpg/factory-.git /root/factory
cd /root/factory

# 2. Создать свою ветку и worktree (или просто работать в клоне)
git checkout -b agent/server
git branch --set-upstream-to=origin/agent/server

# 3. Скопировать .env.example в .env и добавить HEYGEN_API_KEY
cp .env.example .env
nano .env   # добавить HEYGEN_API_KEY=..., HEYGEN_BASE_URL=...

# 4. Установить зависимости
python3 -m pip install -r requirements.txt 2>/dev/null || true

# 5. Проверить nginx и аудио
curl -I http://178.172.137.203/audio/voice_nose.wav   # должен быть 200 OK
```

### Для agent-git
```bash
# 1. Клонировать репозиторий
git clone https://github.com/proosandr-jpg/factory-.git /path/to/agent-git
cd /path/to/agent-git

# 2. Создать свою ветку
git checkout -b agent/git

# 3. На GitHub защитить ветку main (Settings → Branches → Add rule)
#    - Require a pull request before merging
#    - Require approvals: 1
#    - Dismiss stale approvals on new commits
```

## Шаг 1: Ежедневная рутина

Каждый агент перед началом работы:

```bash
# 1. Свежее состояние из origin
git checkout main
git pull origin main

# 2. Прочитать доску задач
cat COORDINATION.md

# 3. Выбрать задачу со статусом "ожидает" или "заблокировано" (если зависимости готовы)
cat tasks/task-NNN.md   # прочитать границы и критерии приёмки

# 4. Перейти на свою ветку
git checkout agent/<имя>   # например: agent/server
git pull origin agent/<имя>
```

## Шаг 2: Взятие задачи в работу

1. Отредактировать `COORDINATION.md`: статус задачи → `в работе`, ответственный → ваш агент.
2. Сделать коммит обновления COORDINATION.md в свою ветку.
3. Запушить ветку:
   ```bash
   git add COORDINATION.md
   git commit -m "coord: задача task-NNN взята в работу agent-<имя>"
   git push origin agent/<имя>
   ```

## Шаг 3: Выполнение задачи

- Работать **только** в файлах, указанных в разделе "Границы" task-файла.
- Не трогать файлы других агентов без согласования.
- `.env` с реальными ключами **никогда не коммитить** (в .gitignore).

## Шаг 4: Завершение задачи

1. Закоммитить все изменения в свою ветку.
2. Запушить в origin:
   ```bash
   git add .
   git commit -m "feat: task-NNN завершено agent-<имя>"
   git push origin agent/<имя>
   ```
3. Обновить `COORDINATION.md`: статус задачи → `на проверке`.
4. Закоммитить и запушить обновление COORDINATION.md.

## Шаг 5: Ревью и мерж (только agent-git)

`agent-git` выполняет:
1. Проверяет ветку агента-владельца задачи на соответствие границам.
2. Создаёт Pull Request на GitHub из `agent/<имя>` в `main`.
3. После одобрения мержит в `main`.
4. Обновляет `COORDINATION.md`: статус → `завершено`.
5. Удаляет ветку агента на GitHub (опционально).

## Шаг 6: Синхронизация после мержа

Все агенты после мержа в main:
```bash
git checkout main
git pull origin main
git checkout agent/<имя>
git merge main   # или rebase
```

## Правила

| Правило | Описание |
|---------|----------|
| Один коммит = одна задача | Не смешивайте задачи в одном коммите. |
| Никогда не коммитить в main напрямую | Только через мерж от agent-git. |
| .env не в git | Реальные ключи остаются локально. |
| COORDINATION.md — единая правда | Если в файле написано иначе, чем в действительности — обновлять файл. |
| Ветки не пересекаются | Каждый агент работает только в своей ветке `agent/<имя>`. |

## Чат между агентами

Если нужно задать вопрос другому агенту — обновите поле "Ждёт от" в `COORDINATION.md` и дождитесь ответа там же. Прямые сообщения не используются.