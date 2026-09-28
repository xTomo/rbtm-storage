# Ревью rbtm-storage (сентябрь 2026)

Ветка: `review/storage-cleanup`. База: `fix/hdf5-v2-short-experiment-chunk` @ `cfae099` (от `dev` @ `a9cf55b`).
Общий документ по стыкам модулей: `xtomo/plans/REVIEW-2026-09-cross-module.md` (C1–C12).

Что смотрели: `storage/hdf5_v2.py` (writer HDF5 v2), `storage/routes/*`, `filesystem.py`, `db.py`, `rewrite.py`,
Docker/nginx/supervisord, README, тесты. Ссылки `file:line` — по состоянию базы.

---

## 1. Главное

| # | Проблема | Где | Риск |
|---|---|---|---|
| 1 | **`None` в метаданных кадра роняет запись.** Drivers подставляют `None` при сбое чтения датчика (`_safe_read`); `float(None)` → `TypeError` → 500 → drivers ретраят 3× и останавливают эксперимент. `None` в `present`/`shutter.open` тихо становится `False`. | `hdf5_v2.py:341-349` | blocker |
| 2 | **Кадр вставляется в Mongo до записи HDF5, без идемпотентности.** При 500 каждый ретрай drivers добавляет дубль документа в `frames`; web показывает дубли строк. | `routes/storage.py:38-44` | high |
| 3 | **`mapping/*` только при успешном finish**; ошибка finalize лишь логируется. Прерванный эксперимент recon-reader не читает. Повторный finalize падает (`del mapping[mode_name]` — ключ без `_indices`). | `routes/experiments.py:87-102`, `hdf5_v2.py:455-459` | high |
| 4 | **checkpoint-пары и `segment_ids` не соответствуют документации**: пары строятся по каждому empty-кадру серии (K·series_length дублей), data-кадр ищется по углу empty; `segment_ids` для data = число empty-кадров, для data_check = счётчик, periodic empty = 0. `_compute_segment_id` пересканирует timeline на каждый кадр (O(N²)). | `hdf5_v2.py:362-425, 479-511` | high |
| 5 | **В HDF5 всегда дефолтные детектор и источник**: `filesystem.create_experiment` не передаёт `detector_info` (`pixel_size=4.25e-3`, `detector_model=''`), `source_info` в `add_frame_v2` извлекается и не пишется. Реальные значения есть только в Mongo. | `filesystem.py:46`, `hdf5_v2.py:171-200, 326` | high |
| 6 | Факт > `total_frames` → `RuntimeError` h5py (resize > maxshape) без внятного текста; `data_count_per_step` обязателен в `compute_total_frames`, drivers допускают отсутствие. | `hdf5_v2.py:125, 337` | med |
| 7 | pymongo 2.x API (`insert/update/remove/count`) при `pymongo==3.13`: DeprecationWarning, на 4.x упадёт. `delete_experiment` при «не найдено» продолжает удаление и отвечает `success`. | `routes/experiments.py:64,91,120-138`, `routes/storage.py:38` | med |
| 8 | `finish`: литерал `'Experiment was finished successfully'` дублирует `SUCCESSFUL_STOP_MSG` drivers; `json_msg['exception message']` без `.get`; существование эксперимента не проверяется. | `routes/experiments.py:87-104` | med |
| 9 | Мёртвое: `rewrite.py` (обход `data/experiments` и `g.db` на уровне модуля при импорте), `pyframes.delete_frame`, Flask-роут `POST /storage/png/get` (PNG и `.h5` отдаёт nginx-alias), `get_experiment_info_v2`/`is_hdf5_v2` не вызываются (версия — по `.v2`-маркеру). | `rewrite.py:11,48-51`, `pyframes.py:119-126`, `storage.py:73-88` | low |
| 10 | Инфраструктура: PNG в сыром `Thread` на кадр без пула; `errors.py` печатает traceback на 400/404; нет `.dockerignore` (`COPY .` тянет `.git`, `data/`, `logs/`); `storage/conf.py` не в git и не генерируется — на свежем клоне импорт падает; `requirements.txt` (Flask 0.12, h5py 2.8) нерабочий; `runserver.py debug=True`; `server` без `depends_on: database`; regex `.h5` без экранирования точки. | `pyframes.py:50`, `errors.py:9,14`, `Dockerfile:18-21`, `docker-compose.yml`, `storage_nginx.conf:19` | low–med |

---

## 2. Архитектура

nginx (:5006) → gunicorn 4 workers × 2 threads (:5007) → Flask (`storage:app`, создаётся при импорте пакета).
Один HDF5-файл на эксперимент; все writer-операции (`add_frame_v2`, `finalize`) — под `portalocker.Lock(<h5>.lock, 60 с)`;
`create_experiment_hdf5_v2` без лока, `.v2`-маркер пишется после закрытия файла, но ответ `/create` уходит после маркера —
для последовательного драйвера окна нет. nginx отдаёт `…/frames/<fid>/png` и `…/<id>.h5` напрямую (`alias`), минуя Flask и без проверки прав.

Контракт с drivers и recon — см. cross-module §2, §3 (C1–C5, C7, C9, C10). Round-trip writer → reader: `xtomo/scripts/check_hdf5_contract.py`.

---

## 3. По компонентам

### 3.1 `hdf5_v2.py`
- Датасеты и dtype: `metadata/*` скаляры (строки bytes, числа int64/float64 — README заявляет int32/float32), `timeline/*` resizable с `maxshape=(total,)`, `images/all` `(total,H,W)` uint16 gzip-4, chunk по `series_length`/эвристике (клампинг из fix-ветки), `mapping/*_indices` int32.
- Reader recon читает только `metadata/*`, `timeline/{modes,angles,frame_numbers}`, `images/all`, `mapping/*_indices`; `segment_ids`, `checkpoint_*`, температуры, позиции никем не читаются (C1).
- Гонки: инкремент `current_frame_index` и ленивое создание `images/all` — под локом, безопасно для 4 воркеров; при упавшей попытке `timeline/angles` может остаться длиннее остальных на 1 (частичный resize).
- Строки под h5py 2.x читались бы как `str` и `str(x,'utf8')` падал бы — актуально только для `requirements.txt`.

### 3.2 Роуты
- `/storage/experiments/get` — `dumps(cursor)` материализует всю коллекцию (web и recon запрашивают `{}`).
- `/storage/experiments/create` — «already exists» с HTTP 200 и `result != 'success'` (drivers считают это ошибкой и ретраят); `finished=False` ставится после `dumps` → в `exp_info_json` нет `finished`.
- `/storage/frames/post` — см. §1 п.2; `np.load` и `add_frame` без try → generic 500.
- `/storage/frames_info/get` — сортировка `frame.number` как строки, корректна благодаря zero-pad.
- `DELETE /storage/experiments/<id>` — без аутентификации, `rmtree` всего каталога.

### 3.3 Docker/деплой
См. §1 п.10. `client_max_body_size 50M` при кадре 4096²×2 = 32 МБ — запас есть. `proxy_read_timeout 130` vs `lock_timeout 60` и таймаут drivers 120 с — запас 10 с.

---

## 4. План работ (ветка `review/storage-cleanup`)

| Коммит | Содержание | Проверка |
|---|---|---|
| None-safe метаданные | NaN для float, 0/False с предупреждением для int/bool, округление `horizontal position`, один сбор значений | `tests/test_hdf5_v2.py` |
| finalize | идемпотентность; одна checkpoint-пара на серию (первый data_check ↔ последний предыдущий data с тем же углом) | тесты, round-trip |
| segment_ids | документированная семантика (−1 / 0 / k-я вставка), O(1) через attrs | тесты |
| compute_total_frames | default 1 для `data_count_per_step` / `count per step`; понятная ошибка при факт > total | тесты |
| detector/source в HDF5 | `detector_info` из документа эксперимента при create; source/detector с первого кадра | тесты |
| frames/post | HDF5 → upsert по `(exp_id, frame.number)`; JSON-ошибка 500 без вставки документа | mongomock (если удалось) |
| finish | константа, `.get`, finalize при любом завершении, `stopped_with_error`, 404/500 | — |
| pymongo 3.x API, delete_experiment | `insert_one/update_one/delete_many/count_documents`, ранний return | — |
| мёртвый код | `rewrite.py`, `delete_frame`, `scipy.ndimage.filters` | grep |
| инфраструктура | пул PNG, errors.py, `.dockerignore`, `conf.py` silent + env, `requirements.txt`, `runserver` debug по env, `depends_on`, nginx regex | — |
| README | segment_ids, checkpoint, finalize при стопе, `.v2`/`.lock`, dtype, nginx-alias в таблице API | — |

Не делаем без отдельного решения: аутентификация роутов и nginx-alias; тип `frame.number`; замена `.v2`-маркера;
двухуровневая очередь PNG; удаление `POST /storage/png/get` (помечен неиспользуемым).

---

## 5. Статус на 22.09.2026

Ветка `review/storage-cleanup`: 18 коммитов поверх `fix/hdf5-v2-short-experiment-chunk` (`7a38450` … `e5cecc9`), рабочее дерево чистое.
Сделано всё из §4; сверх плана — повтор последнего кадра не пишется в HDF5 второй раз (`e5cecc9`, потерянный ответ после успешной записи).

Проверено локально:

| Проверка | Результат |
|---|---|
| `python -m pytest tests -q` (h5py 3.11, mongomock, Flask test client) | 29 passed (было 4) |
| Round-trip writer → reader recon (`xtomo/scripts/check_hdf5_contract.py`) | 27/27: `segment_ids` `[-1,-1,0,0,0,0,1,1,1,1,1,2,2,2,2]`, 2 checkpoint-пары с совпадающими углами, finalize ×2, чтение прерванного эксперимента, `None` в метаданных, лишний кадр → `ValueError` с текстом |
| `add_frame_v2` с `None` в `chip_temp`/`angle position` | NaN в timeline, запись успешна |
| `/storage/frames/post` при ошибке HDF5 | 500 JSON, документ в Mongo не создаётся; повтор — upsert по `(exp_id, frame.number)` |
| `/storage/experiments/finish` при стопе | `finished=False`, `stopped_with_error`, `mapping/*` создан |

NOT VERIFIED — требует стенда robotom: реальный прогон drivers → storage (в т.ч. `stop` посередине: ожидается `finished=False`,
`stopped_with_error`, `mapping/` в файле); гонки 4×2 gunicorn; nginx-alias после правки regex; сборка образа с `.dockerignore` и без `storage/conf.py`
(`MONGODB_URI` из окружения, дефолт `mongodb://database:27017` — сверить с текущим `conf.py` на хосте перед пересборкой).

Не сделано (решение пользователя): аутентификация роутов/alias, `frame.number` как int, удаление `POST /storage/png/get`, `.v2`-маркер.

---

## 6. Межмодульные контракты (сторона storage)

- **Вход от drivers**: `/experiments/create` (JSON web + `detector_model`, `pixel_size`), `/frames/post` (multipart, `None` возможен в любом числовом поле), `/experiments/finish` (`message` = `SUCCESSFUL_STOP_MSG` или текст стопа + `error`/`exception message`).
- **Выход для recon**: HDF5 v2 по nginx-alias `/storage/experiments/<id>.h5` или bind-mount `/exp_src`; reader требует `mapping/*` либо (после правок recon) строит индексы из `timeline/modes`; checkpoint-пары и `segment_ids` reader не использует.
- **Выход для web**: `/experiments/get` (весь список), `/frames_info/get` (сортировка строкой), PNG по nginx-alias, `.h5` по alias через `rbtm-proxy`.
- **Число кадров**: `compute_total_frames` == цикл drivers (обе моды) == JS-оценка в web (C3).
