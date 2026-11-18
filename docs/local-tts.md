# Локальные (offline) TTS-движки для русского языка: факты и выбор

**Дата проверки:** 31.10.2026.
**Условия задачи:** Windows, Python 3.13.15 (проверено локально), без GPU, коммерческое использование (Instagram пластического хирурга), ролики 15–20 с, желательно клонирование голоса по эталону 20–30 с.

**Контекст проекта.** Сейчас озвучка идёт в облако: `pipeline.py:47` — `TTS_MODEL = "resemble-ai/chatterbox-multilingual"`, `pipeline.py:222-269` — `generate_audio()` с `exaggeration: 0.45` и `cfg_weight: 0.5`, сборка в 24 кГц mono. Эталон голоса — `assets/voice/reference.wav` (`pipeline.py:44`), язык — `TTS_LANGUAGE = "ru"` (`pipeline.py:45`). Обзор облачных вариантов — в `docs/tts.md`; этот файл — про локальную замену.

**Уровни доказательности, используемые ниже:**

| Уровень | Что это |
|---|---|
| **A** | Первичные машиночитаемые факты: метаданные PyPI (JSON API), файлы `LICENSE`/`COPYING`/`LICENSE.txt` в репозитории, `voices.json` на Hugging Face, HTTP-заголовки размеров файлов |
| **B** | Официальная документация и README авторов проекта |
| **C** | Issue tracker и обсуждения (косвенные измерения, сообщения пользователей) |
| **D** | Блоги и пересказы — только как лид, в выводы не идут |
| **не подтверждено** | Источника нет; утверждение высказано как гипотеза |

---

## 1. Сводная таблица

| Движок | Пакет (версия, дата) | Python | torch | Вес загрузки | Русский | Клонирование | Лицензия (код / веса) | Коммерческое использование | CPU |
|---|---|---|---|---|---|---|---|---|---|
| **Piper** | `piper-tts` 1.8.0 (04.09.2026) | `>=3.9`, classifiers 3.13, wheel `cp39-abi3` | **не нужен** (`onnxruntime>=1,<2`, `pathvalidate`) | 32,5 МБ пакет + 60,3 МБ на голос | **да**, 4 голоса `ru_RU` (`dmitri`, `denis`, `irina`, `ruslan`) | **нет** (VITS, 1 спикер на модель) | код **GPL-3.0-or-later** / голоса: CC0, CC0, Unknown, CC BY-NC-SA 4.0 | да, с обязательствами GPL; голоса `dmitri`/`denis` — CC0, `ruslan` — нельзя, `irina` — неясно | да (onnxruntime); скорость не измерена — **не подтверждено** |
| **Silero** | `silero` 0.5.5 (03.02.2026) | `>=3.7`, classifiers 3.13 | **да**: `torch>=1.12`, `omegaconf`, `numpy` | `v5_cis_base.pt` 87,4 МБ; `v5_ru.pt` 138,6 МБ; `v4_ru.pt` 38,2 МБ + torch | **да** (`aidar`, `baya`, `kseniya`, `xenia`, `eugene`) | **нет** (фиксированные спикеры) | базовый `LICENSE` — **CC BY-NC-SA 4.0**; `LICENSE_CIS` — **MIT** (только `v5_cis_base*`) | только `v5_cis_base`/`v5_cis_base_nostress` (MIT); `v5_ru`/`v4_ru` — **нельзя** (NC) | нужен AVX2; скорость — **не подтверждено** |
| **Coqui XTTS-v2** | `coqui-tts` 0.28.0 (19.10.2026); оригинальный `TTS` 0.22.0 — Python `<3.12`, не подходит | `>=3.10,<3.15`, classifiers 3.13/3.14 | **да**, ставится отдельно (с 0.27.4 torch убран из core-зависимостей) | torch (wheel 2.15.0 cp313 win — 120,9 МБ) + веса ≈ **1,98 ГБ** (`model.pth` 1781,4 МБ + `dvae.pth` 200,8 МБ + `speakers_xtts.pth` 7,4 МБ) | **да** (17 языков) | **да**, «6-second audio clip» (в docs idiap — «3-second») | код **MPL-2.0** / веса **CPML 1.0.0** | **нет**: «This license allows only non-commercial use of a machine learning model and its outputs» | не проверено — **не подтверждено** |
| **Chatterbox Multilingual** | `chatterbox-tts` 0.1.7 (26.03.2026) | `>=3.10`; README: тестировали на 3.11; на 3.13 — **не подтверждено** (но `torch==2.6.0` имеет cp313 win-wheel) | **да**: `torch==2.6.0` (<3.14) + `transformers==5.2.0` | `t3_mtl23ls_v2` 2044,7 МБ + `s3gen.pt` 1008,2 МБ + `ve.pt` 5,4 МБ ≈ **3,0 ГБ** + torch | **да** (23 языка, `language_id="ru"`) | **да**, по эталону (cond prompt) | код и веса **MIT** (HF-тег `license:mit`) | **да** | ветка CPU есть в коде; скорость на CPU — **не подтверждено** |
| **OmniVoice** | `omnivoice` 0.2.1 (16.07.2026) | `>=3.10`, classifiers только 3.10/3.11 → 3.13 **не заявлен** | **да**: `torch>=2.4`, `transformers>=5.3` | `model.safetensors` 2,34 ГБ + `audio_tokenizer` 768 МБ ≈ **3,1 ГБ** | **да** (`docs/languages.md`, строка 481: `| 481 | Russian | ru |`) | **да**, zero-shot по `ref_audio`+`ref_text`, рекомендуют 3–10 с | **Apache-2.0** | **да** | официально CUDA/MPS/XPU; на CPU 24 с аудио ≈ **17 мин** (issue #288) → практически непригоден |
| **F5-TTS** | `f5-tts` 1.1.22 (23.07.2026) | не задан | **да**, `torch>=2.0` | веса + torch | **нет** (en/zh) | да | код **MIT** / веса **CC-BY-NC** | **нет** (веса NC) | не рассматривался |
| **VoxCPM2** | `voxcpm` 2.0.3 (11.05.2026) | `>=3.10`, **`<3.13`** у upstream | **да**, `torch>=2.5` | ~2B параметров, VRAM ~8 ГБ | да | да | Apache-2.0 | да | **нет**: требует CUDA ≥ 12.0 |
| **Fish Speech** | `fish-speech` 0.1.0 (07.07.2025, единственный релиз, неофициальный пакет) | — | да | — | да | да | **FISH AUDIO COMMUNITY LICENSE 1.0** | только research/non-commercial; коммерческая — по отдельной лицензии | не рассматривался |
| **CosyVoice** | PyPI `cosyvoice` 0.0.8 — **неофициальный форк**; официально — установка из GitHub | — | да | — | да | да | официальный репозиторий **Apache-2.0**; PyPI-форк **GPL-3.0** | да (Apache-2.0), но ставить только из GitHub | **не подтверждено** |
| *Kokoro (справочно)* | `kokoro` 0.9.4 | **`<3.13`** | да | — | **нет** | **нет** | Apache-2.0 | да | — |

---

## 2. Детали по кандидатам

### 2.1. Piper — лёгкий CPU-движок без torch

- **Пакет:** `piper-tts` 1.8.0, опубликован 04.09.2026, 11 версий, home page — `OHF-voice/piper1-gpl`. `requires_python >=3.9`, классификаторы включают Python 3.13. Колесо для Windows: `piper_tts-1.8.0-cp39-abi3-win_amd64.whl`, 32,5 МБ, тег **cp39-abi3** → ставится на 3.13 без сборки. *(A: https://pypi.org/pypi/piper-tts/json)*
- **Зависимости:** только `onnxruntime<2,>=1` и `pathvalidate`. **torch не нужен** — это ключевое отличие от остальных кандидатов. *(A: там же, `requires_dist`)*
- **Русские голоса:** в `voices.json` (178 голосов всего) ровно 4 русских, все `medium`, по 1 спикеру, 22 050 Гц, по 60,3 МБ `.onnx`: `ru_RU-denis-medium`, `ru_RU-dmitri-medium`, `ru_RU-irina-medium`, `ru_RU-ruslan-medium`. *(A: https://huggingface.co/rhasspy/piper-voices/raw/main/voices.json)*
- **Лицензии голосов** (из `MODEL_CARD` каждого голоса): `dmitri` — **CC0**, `denis` — **CC0**, `ruslan` — **CC BY-NC-SA 4.0** (датасет `ruslan-corpus.github.io`), `irina` — **License: Unknown** (датасет RHVoice). Все четыре — финетюн с английского `lessac medium`. *(A)*
- **Лицензия кода:** `COPYING` = GNU GPL v3, в метаданных PyPI — `GPL-3.0-or-later`. *(A)*
- **Клонирование:** отсутствует. Архитектура — VITS, каждый голос = отдельная модель с фиксированным числом спикеров (1 для всех русских), параметра эталона голоса в API нет. *(A: структура voices.json — `num_speakers: 1`; B: VOICES.md — «Piper is intended for personal use and text to speech research only»)*
- **Важное предупреждение upstream** (`docs/VOICES.md`): «The `MODEL_CARD` file for each voice contains important licensing information. Piper is intended for personal use and text to speech research only; we do not impose any additional restrictions on voice models. Some voices may have restrictive licenses, however, so please review them carefully!» *(B: https://github.com/OHF-voice/piper1-gpl/blob/main/docs/VOICES.md)* — формально это не лицензия, а заявление о назначении; лицензия кода GPL-3.0 коммерческое использование разрешает. Расхождение зафиксировано, требует юридической проверки.

### 2.2. Silero — качественный русский, но тяжёлый и с NC-лицензией по умолчанию

- **Пакет:** `silero` 0.5.5 (03.02.2026), официальный (`pip install silero`, `from silero import silero_tts`), `requires_python >=3.7`, классификаторы включают 3.13. Зависимости: `torch>=1.12.0`, `omegaconf>=2.1.0`, `numpy>=1.23.0`. *(A: https://pypi.org/pypi/silero/json)*
- **Лицензионная развилка:** корневой `LICENSE` — **CC BY-NC-SA 4.0** («Attribution-NonCommercial-ShareAlike 4.0 International»), `LICENSE_CIS` — **MIT** (© 2025-present Silero Team). README: модели `v5_cis_base` и `v5_cis_base_nostress` «published under MIT licence» и включают русских спикеров с префиксом `ru_`; `v5_cis_ext` — CC-NC-BY. *(A: https://github.com/snakers4/silero-models — файлы LICENSE и LICENSE_CIS)*
- **Русские голоса:** `v5_5_ru` (`aidar`, `baya`, `kseniya`, `xenia`, `eugene`; автоударение, омографы, разметка вопросов, 8/24/48 кГц), а также `v5_4_ru`, `v5_3_ru`, `v5_2_ru`, `v5_ru`, `v4_ru`. Размеры: `v5_ru.pt` 138,6 МБ, `v5_cis_base.pt` 87,4 МБ, `v4_ru.pt` 38,2 МБ. *(A: HEAD Content-Length; B: models.yml)*
- **Клонирование:** нет. Набор голосов фиксирован, API принимает `speaker`, а не эталонный аудиофайл. *(A: сигнатура `silero_tts(...).apply_tts(speaker=...)` в README)*
- **Офлайн:** модели скачиваются по требованию через `torch.hub` и кэшируются → для полностью offline нужен предварительный прогрев кэша. Минимальные требования: PyTorch-совместимая система + **AVX2**. *(B: README)*

### 2.3. Coqui XTTS-v2 — лучший клон, но коммерчески запрещён

- **Пакет:** актуальный форк — `coqui-tts` 0.28.0 (19.10.2026), лицензия пакета **MPL-2.0**, `requires_python >=3.10,<3.15`, классификаторы 3.13 и 3.14, 22 core-зависимости **без torch** (torch ставится отдельно с 0.27.4). Классификатор ОС — только «POSIX :: Linux», но README: «should also work on Mac and Windows», Windows-wheels есть с 0.24.2. Оригинальный пакет `TTS` 0.22.0 (12.12.2023) требует `>=3.9.0,<3.12` → Python 3.13 **не поддерживает**. *(A: https://pypi.org/pypi/coqui-tts/json, https://pypi.org/pypi/TTS/json)*
- **Русский:** да, 17 языков. **Клонирование:** «Voice cloning with just a 6-second audio clip» (HF-карточка). Расхождение: документация форка говорит про «3-second audio clip» — зафиксировано, для нас не критично (эталон 20–30 с покрывает оба варианта). 24 кГц. *(B: https://huggingface.co/coqui/XTTS-v2, https://coqui-tts.readthedocs.io/en/latest/models/xtts.html)*
- **Лицензия весов — блокер.** `LICENSE.txt` в репозитории весов = **Coqui Public Model License 1.0.0**, первая же строка: «This license allows only non-commercial use of a machine learning model and its outputs». Далее: «Non-commercial purposes include any of the following uses of the model or its output, but only so far as you do not receive any direct or indirect payment arising from the use of the model or its output», и отдельно — «Use of the model to train other models for commercial use is not a non-commercial purpose». *(A: https://huggingface.co/coqui/XTTS-v2/raw/main/LICENSE.txt)*
- Сайт лицензии `https://coqui.ai/cpml` и `https://coqui.ai/cpml.txt` отдают **404** (компания закрылась в январе 2024), поэтому единственный доступный первоисточник — копия `LICENSE.txt` в весах. Коммерческую лицензию купить больше не у кого — это подтверждают обсуждения в трекере. *(C: https://github.com/coqui-ai/TTS/discussions/4304)*
- **Вывод:** для Instagram-проекта (прямая или косвенная оплата за результат) XTTS-v2 **нельзя** использовать без отдельного договора, которого не существует.

### 2.4. Chatterbox Multilingual — единственный «чистый» вариант с клонированием

- **Пакет:** `chatterbox-tts` 0.1.7 (26.03.2026), лицензия **MIT**, `requires_python >=3.10`, 18 зависимостей: `torch==2.6.0` (для Python <3.14), `transformers==5.2.0`. Для Python 3.13 есть готовое колесо `torch-2.6.0-cp313-cp313-win_amd64.whl` → установка разрешима. README: «developed and tested Chatterbox on Python 3.11» → работа именно на 3.13 **не подтверждена**. *(A: PyPI JSON + файлы torch 2.6.0; B: README)*
- **Русский:** да, 23 языка (Multilingual V3, 0.5B), `language_id="ru"`. *(B: README, HF-тег)*
- **Клонирование:** да, по эталонному аудио (cond prompt + `ve`-эмбеддинг). Эталон 20–30 с укладывается с запасом.
- **CPU поддерживается кодом явно.** В `src/chatterbox/mtl_tts.py` (ветка master): `REPO_ID = "ResembleAI/chatterbox"`, `DEFAULT_MULTILINGUAL_T3_MODEL = "t3_mtl23ls_v2.safetensors"`, `def __init__(..., device: str, ...)`, и отдельная ветка загрузки:
  `# Always load to CPU first for non-CUDA devices to handle CUDA-saved models` / `if device in ["cpu", "mps"]: map_location = torch.device('cpu')`, а также fallback `if device == "mps" and not torch.backends.mps.is_available(): ... device = "cpu"`. Коммит `fix: add map_location to torch.load for CPU/MPS support in multilingual` — 09.03.2026. *(A: https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/mtl_tts.py)*
- **Важная оговорка по версии:** коммит `Add opt-in v3 multilingual checkpoint...` — 01.05.2026, то есть **позже** релиза 0.1.7 (26.03.2026). Значит в pip-версии 0.1.7 ожидается чекпойнт v2 (`t3_mtl23ls_v2.safetensors`), а v3 доступен только из master. Размеры обоих файлов одинаковы (2044,7 МБ), так что оценка загрузки не меняется. *(A: коммиты + HEAD Content-Length)*
- **Размер загрузки:** `t3_mtl23ls_v2.safetensors` 2044,7 МБ + `s3gen.pt` 1008,2 МБ + `ve.pt` 5,4 МБ + `conds.pt` 0,1 МБ ≈ **3,0 ГБ** плюс torch. *(A: HEAD-запросы к https://huggingface.co/ResembleAI/chatterbox)*
- **Скорость на CPU — не подтверждена.** Прямых замеров multilingual-модели на CPU в трекере нет; README упоминает «Chatterbox-Nano 110M — 3x faster than realtime on 8 CPU cores», но Nano существует **только для английского**. *(B: README; отсутствие данных — явная лакуна)*

### 2.5. OmniVoice — Apache-2.0 и русский, но на CPU непригоден по скорости

- **Пакет:** `omnivoice` 0.2.1 (16.07.2026), **Apache-2.0**, `requires_python >=3.10`, `torch>=2.4`, `transformers>=5.3.0`, классификаторы только 3.10/3.11 → Python 3.13 официально **не заявлен**. *(A: https://pypi.org/pypi/omnivoice/json)*
- **Русский:** подтверждён — `docs/languages.md`: `| 481 | Russian | ru | rus | 20338.5 |`. **Клонирование:** zero-shot по `ref_audio` + `ref_text`, рекомендуемая длина эталона 3–10 с. *(A/B: https://github.com/k2-fsa/OmniVoice)*
- **Размер:** `model.safetensors` 2,34 ГБ + `audio_tokenizer/model.safetensors` 768 МБ ≈ **3,1 ГБ**. *(A: HEAD)*
- **CPU — решающий минус.** README заявляет «RTF as low as 0.025 (40x faster than real-time)», но это бенчмарк на **H100**, а инструкции по установке описывают только CUDA / Apple MPS / Intel XPU. Упоминание `asr_device="cpu"` относится к ASR-модели (Whisper), а не к синтезу. Прямое измерение в трекере (issue #288, 22.10.2026, M1 MacBook Air, CPU, 24 с выходного аудио): **float16 ≈ 25 мин, float32 ≈ 17 мин**. Это ~40–60× медленнее реального времени. *(C: https://github.com/k2-fsa/OmniVoice/issues/288)*

### 2.6. Остальные — почему отпадают

- **F5-TTS** (`f5-tts` 1.1.22): код MIT, но «The pre-trained models are licensed under the CC-BY-NC license» → коммерческое использование весов запрещено; русского в списке языков нет. *(A/B: репозиторий SWivid/F5-TTS)*
- **VoxCPM2** (`voxcpm` 2.0.3): Apache-2.0 и русский есть, но «Requirements: Python ≥ 3.10 (<3.13), PyTorch ≥ 2.5.0, CUDA ≥ 12.0», VRAM ~8 ГБ, 2B параметров → не подходит по Python 3.13 и по отсутствию GPU. *(B: https://github.com/OpenBMB/VoxCPM)*
- **Fish Speech** (`fish-speech` 0.1.0, единственный релиз 07.07.2025, без project_urls → пакет неофициальный): «FISH AUDIO COMMUNITY LICENSE 1.0» — бесплатно для research/non-commercial, коммерческое только по Community Commercial License при выручке ниже порога; Hosted Services — отдельная лицензия. *(A: LICENSE в fishaudio/fish-speech)*
- **CosyVoice:** официальный `FunAudioLLM/CosyVoice` — Apache-2.0, 9 языков включая русский, zero-shot клонирование; но PyPI-пакет `cosyvoice` 0.0.8 (2024) — **неофициальный форк** под GPL-3.0. Ставить можно только из GitHub; поддержка Python 3.13 и CPU — **не подтверждено**. *(A: метаданные PyPI; B: репозиторий)*
- **Kokoro** (`kokoro` 0.9.4): `requires_python <3.13` и **нет русского** — только как справочная точка. *(A: PyPI JSON)*

---

## 3. Рекомендация

### Вариант с клонированием голоса: `chatterbox-tts` 0.1.7 (MIT)

Единственный движок, у которого одновременно сходятся все жёсткие условия задачи: русский подтверждён в официальном списке 23 языков, клонирование по короткому эталону (20–30 с — с запасом), лицензия **MIT и на код, и на веса** (коммерческое использование разрешено без доплат), и в коде есть явная ветка загрузки на CPU (`mtl_tts.py`, `map_location=torch.device('cpu')`).

**Обоснование выбора против альтернатив:** XTTS-v2 отпадает по лицензии (CPML: «only non-commercial use»), OmniVoice — по скорости на CPU (24 с аудио ≈ 17 мин, issue #288), F5-TTS — по NC-весам и отсутствию русского, VoxCPM2 — по `Python <3.13` и CUDA, Fish Speech — по некоммерческой лицензии.

**Цена и риски, которые надо принять осознанно:**
1. Загрузка ≈ **3,0 ГБ** весов + torch (против 93 МБ у Piper). Первый запуск требует сети, дальше — offline из кэша HF.
2. **Скорость на CPU не подтверждена.** Ожидание: медианная 0.5B-модель на CPU синтезирует медленнее реального времени; для ролика 15–20 с это могут быть минуты. **Обязательный шаг перед внедрением** — замер на целевой машине: сгенерировать 20 с русской речи, замерить wall-clock и RTF. Если RTF > 3–5, локальный вариант не имеет смысла для потока и остаётся облако.
3. Python 3.13 официально не тестировался (README: тестировали на 3.11). Установка разрешима — `torch==2.6.0` имеет `cp313-win_amd64` wheel — но совместимость `transformers==5.2.0` на 3.13 нужно проверить фактической установкой.
4. В pip-версии 0.1.7, скорее всего, только чекпойнт **v2** (v3 добавлен коммитом от 01.05.2026, позже релиза). Качество v2 на русском не измерялось.
5. Юридически MIT покрывает модель, но **не** покрывает права на сам клон голоса: нужно письменное согласие человека, чей голос клонируется (для клиники — согласие врача), иначе риск по ст. 152.1 ГК РФ о неприкосновенности изображения/голоса.

### Вариант без клонирования: `piper-tts` 1.8.0 + голос `ru_RU-dmitri-medium` (CC0)

Самый дешёвый по ресурсам и самый предсказуемый по установке вариант: **torch не нужен вообще** (только `onnxruntime` + `pathvalidate`), колесо `cp39-abi3` ставится на Python 3.13 как есть, пакет 32,5 МБ, голос 60,3 МБ, инференс на CPU через onnxruntime. Лицензия голоса `dmitri` — **CC0**, то есть коммерческое использование разрешено явно и без оговорок.

**Оговорки:**
- Код Piper — **GPL-3.0-or-later**. Для внутреннего рендера роликов (результат — видео, а не программа) обязательства не срабатывают; при передаче заказчику модифицированного приложения/библиотеки потребуется раскрытие исходников. Это правовая оценка, а не юридическое заключение — при поставке «коробки» нужна консультация юриста.
- В `docs/VOICES.md` upstream пишет: «Piper is intended for personal use and text to speech research only; we do not impose any additional restrictions on voice models» — это заявление о назначении, а не лицензия; GPL-3.0 коммерческое использование разрешает. Расхождение зафиксировано.
- Голоса `ruslan` (**CC BY-NC-SA 4.0**) и `irina` (**License: Unknown**) для коммерческого проекта **не использовать** — берите только `dmitri` или `denis` (оба CC0).
- Скорость Piper на CPU не измерялась в рамках этой проверки — **не подтверждено**, но архитектурно (onnxruntime, 60 МБ модель) это самый быстрый из рассмотренных вариантов.

**Резерв без клонирования:** `silero` 0.5.5, только модели `v5_cis_base` / `v5_cis_base_nostress` (лицензия **MIT**, `LICENSE_CIS`), русские спикеры `ru_*`. Даёт более живую интонацию и автоударение, но тянет torch (гигабайты) и требует AVX2; базовый `LICENSE` репозитория — CC BY-NC-SA, поэтому использовать можно **только** файлы под MIT, а не `v5_ru`/`v4_ru`.

### Как это соотносится с текущим пайплайном

Локальный движок заменяет только шаг `generate_audio()` (`pipeline.py:222-269`): на выходе нужен файл 24 кГц mono (`pipeline.py:269`), дальше липсинк `bytedance/omni-human` не меняется. Chatterbox отдаёт 24 кГц нативно, Piper — 22 050 Гц (потребуется ресемплинг в 24 кГц, что уже делает ffmpeg-цепочка). Код проекта в рамках этой задачи не изменялся.

---

## 4. Что осталось неподтверждённым

| Вопрос | Почему не закрыт | Как проверить |
|---|---|---|
| Скорость Chatterbox multilingual на CPU (RTF) | Прямых замеров в трекере и README нет; цифра «3× faster than realtime» относится к англоязычной Nano-модели | Замерить локально после установки: 20 с русского текста, `time.perf_counter()` вокруг `model.generate()` |
| Работа `chatterbox-tts` 0.1.7 на Python 3.13 | README заявляет тестирование на 3.11; classifiers не подтверждают 3.13 | Пробная установка в отдельный venv (не в проект) |
| Скорость Piper на CPU | Не измерялась; архитектурная оценка, не бенчмарк | 20 с текста через `python -m piper`, замер |
| Скорость XTTS-v2 на CPU | Не проверялась: движок отсечён по лицензии раньше, чем дошло до бенчмарка | Не требуется, пока лицензия CPML в силе |
| Наличие `ChatterboxMultilingualTTS` в колесе 0.1.7 | Проверен только исходник в git (`src/chatterbox/mtl_tts.py`), состав wheel не вскрывался | `python -m zipfile -l chatterbox_tts-0.1.7-*.whl` или `import chatterbox.mtl_tts` после установки |
| Поддержка CPU у CosyVoice | Официальный репозиторий требует CUDA-сборку; инструкции для CPU нет | Читать `FunAudioLLM/CosyVoice` README целиком + issues |
| Лицензия датасета голоса `irina` (Piper) | В MODEL_CARD стоит «License: Unknown», первоисточник RHVoice не уточняет | Запрос к мейнтейнерам `rhasspy/piper-voices`; до ответа голос не использовать |

---

## 5. Источники

**PyPI (метаданные, проверено 31.10.2026):**
- https://pypi.org/pypi/piper-tts/json
- https://pypi.org/pypi/silero/json
- https://pypi.org/pypi/coqui-tts/json , https://pypi.org/pypi/TTS/json
- https://pypi.org/pypi/chatterbox-tts/json
- https://pypi.org/pypi/omnivoice/json
- https://pypi.org/pypi/f5-tts/json , https://pypi.org/pypi/voxcpm/json , https://pypi.org/pypi/fish-speech/json , https://pypi.org/pypi/cosyvoice/json , https://pypi.org/pypi/kokoro/json , https://pypi.org/pypi/torch/2.6.0/json , https://pypi.org/pypi/torch/json

**Репозитории и документация:**
- Piper: https://github.com/OHF-voice/piper1-gpl , https://github.com/OHF-voice/piper1-gpl/blob/main/docs/VOICES.md , https://github.com/OHF-voice/piper1-gpl/blob/main/COPYING , https://huggingface.co/rhasspy/piper-voices , https://huggingface.co/rhasspy/piper-voices/raw/main/voices.json
- Silero: https://github.com/snakers4/silero-models (LICENSE, LICENSE_CIS, models.yml)
- Coqui: https://huggingface.co/coqui/XTTS-v2 , https://huggingface.co/coqui/XTTS-v2/raw/main/LICENSE.txt , https://coqui-tts.readthedocs.io/en/latest/models/xtts.html , https://github.com/coqui-ai/TTS/discussions/4304
- Chatterbox: https://github.com/resemble-ai/chatterbox , https://raw.githubusercontent.com/resemble-ai/chatterbox/master/src/chatterbox/mtl_tts.py , https://huggingface.co/ResembleAI/chatterbox
- OmniVoice: https://github.com/k2-fsa/OmniVoice , https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md , https://github.com/k2-fsa/OmniVoice/issues/288
- Отклонённые: https://github.com/OpenBMB/VoxCPM , https://github.com/SWivid/F5-TTS , https://github.com/fishaudio/fish-speech , https://github.com/FunAudioLLM/CosyVoice

**Локальные файлы проекта:** `pipeline.py:44-48, 222-269` , `docs/tts.md`.
