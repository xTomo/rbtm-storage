# rbtm-storage

Flask-сервис хранения данных томографических экспериментов. Принимает кадры от `rbtm-drivers-next`, сохраняет их в HDF5 и MongoDB, генерирует PNG-превью.

## Стек

| Компонент | Описание |
|---|---|
| Flask | HTTP API |
| MongoDB | Метаданные экспериментов и кадров |
| HDF5 (h5py) | Бинарные данные кадров |
| matplotlib + scipy | Генерация PNG превью |

## Запуск

```bash
# Разработка
pip install -r requirements.txt
export YOURAPPLICATION_SETTINGS=conf_dev.py  # Unix
set YOURAPPLICATION_SETTINGS=conf_dev.py     # Windows

python runserver.py

# Production (Docker)
docker compose up -d
```

## Структура хранилища

Каждый эксперимент создаёт следующую файловую структуру:

```
data/experiments/<exp_id>/
├── before_processing/
│   ├── <exp_id>.h5          # HDF5 с кадрами
│   └── png/
│       └── <frame_id>.png   # PNG превью для каждого кадра
└── after_processing/
```

---

## Форматы HDF5

### HDF5 v2 (текущий, с 2025)

Все новые эксперименты создаются в формате **HDF5 v2** с единой временной осью (timeline) и типизированными метаданными.

#### Структура HDF5 v2

```
<exp_id>.h5
├── attrs
│   ├── format_version       # "v2" (дублирование для совместимости)
│   ├── created_at           # ISO datetime
│   ├── exp_info_json        # полный MongoDB документ (совместимость)
│   ├── images_initialized   # bool
│   └── total_frames         # int
│
├── metadata/                # Константы эксперимента
│   ├── format_version       # "v2" (явная версия в metadata)
│   ├── experiment_id        # str
│   ├── specimen             # str
│   ├── tags                 # str
│   ├── timestamp            # float64
│   ├── datetime             # str
│   ├── is_advanced          # bool
│   ├── series_length        # int32
│   ├── empty_period         # int32
│   ├── data_total           # int32
│   ├── detector_model       # str
│   ├── pixel_size           # float32 (мм)
│   ├── source_voltage       # float32 (кВ)
│   └── source_current       # float32 (мкА)
│
├── timeline/                # Типизированные массивы, shape (N_total,)
│   ├── frame_numbers        # int64
│   ├── modes                # uint8 (0=dark, 1=empty, 2=data, 3=data_check)
│   ├── angles               # float32 (градусы)
│   ├── exposures            # float32 (мс)
│   ├── timestamps           # float64 (UNIX time)
│   ├── object_present       # bool
│   ├── shutter_open         # bool
│   ├── chip_temp            # float32
│   ├── hous_temp            # float32
│   ├── horizontal_pos       # int32
│   ├── vertical_pos         # int32
│   └── segment_ids          # int32 (-1=dark, 0=initial, 1+=periodic)
│
├── images/
│   └── all                  # uint16[N_total, H, W], chunked, gzip
│
└── mapping/                 # Индексы для быстрого доступа (после финализации)
    ├── dark_indices         # int32[N_dark]
    ├── empty_indices        # int32[N_empty]
    ├── data_indices         # int32[N_data]
    ├── data_check_indices   # int32[N_dc]
    ├── checkpoint_data_indices   # int32[K]
    └── checkpoint_dc_indices     # int32[K]
```

#### Преимущества v2

| Аспект | v1 (legacy) | v2 (current) |
|---|---|---|
| Чтение метаданных кадра | JSON-парсинг × N | Прямой доступ к массивам |
| Доступ к кадрам | N отдельных датасетов | Единый массив, срезы |
| Сортировка по времени | Строковые ключи | Уже отсортированы |
| Поддержка advanced | Раздельные группы | Единая timeline + segment_ids |
| Поиск checkpoint | O(N) по углам | O(1) через mapping |
| Размер метаданных | ~500 байт/кадр | ~60 байт/кадр |

#### Автодетекция версии

```python
from storage.hdf5_v2 import is_hdf5_v2

if is_hdf5_v2(filepath):
    # Чтение v2 (проверяет наличие /timeline и format_version='v2' в metadata)
    # Версия доступна как: f['metadata/format_version'][()].decode('utf8')
else:
    # Чтение v1 (legacy)
```

**Двойная проверка версии:**
- Быстрая: наличие группы `/timeline`
- Точная: `metadata/format_version == 'v2'` (типизированный датасет)

---

### HDF5 v1 (legacy, до 2025)

Старый формат с раздельными группами для каждого типа кадров. Поддерживается только для чтения существующих экспериментов.

#### Структура HDF5 v1

```
<exp_id>.h5
├── attrs: exp_info (JSON метаданные эксперимента)
├── dark/         # Тёмные кадры
│   └── <number>  → dataset + attrs[frame_info]
├── empty/        # Пустые кадры (без образца)
│   └── <number>
├── data/         # Кадры с образцом
│   └── <number>
└── data_check/   # Контрольные кадры (продвинутый режим)
    └── <number>
```

> ⚠️ **Ловушка v1**: `exp_info` содержит полный MongoDB-документ. Параметры эксперимента вложены в ключ `"experiment parameters"`.  
> Правильно: `exp_info['experiment parameters']['series_length']` (не `exp_info['series_length']`).

#### Ключи датасетов (frame_numbers) v1

Датасеты внутри групп именуются строковым представлением глобального `frame_num` с zero-padding:
- `"000020"`, `"000021"`, ... — порядковый номер кадра в рамках всего эксперимента
- Порядок: dark → initial_empty → data[0] → ... → periodic_empty → data_check → data[N] → ...

---

## Форматы экспериментов

### Простой режим (`advanced: false`)

```json
{
  "_id": "uuid-string",
  "specimen": "Название образца",
  "datetime": "07.05.2026 16:00:37",
  "timestamp": 1746619237.0,
  "finished": true,
  "experiment parameters": {
    "advanced": false,
    "DARK":  { "count": 10,  "exposure": 3000.0 },
    "EMPTY": { "count": 10,  "exposure": 3000.0 },
    "DATA":  {
      "step count":     500,
      "exposure":       3000.0,
      "angle step":     0.36,
      "count per step": 1
    }
  }
}
```

**Типы кадров:** `dark`, `empty`, `data`

### Продвинутый режим (`advanced: true`)

```json
{
  "_id": "uuid-string",
  "specimen": "Название образца",
  "datetime": "07.05.2026 16:00:37",
  "timestamp": 1746619237.0,
  "finished": true,
  "experiment parameters": {
    "advanced":            true,
    "exposure":            3000.0,
    "series_length":       10,
    "data_total":          500,
    "data_angle_step":     0.36,
    "data_count_per_step": 1,
    "empty_period":        50
  }
}
```

**Типы кадров:** `dark`, `empty`, `data`, `data_check`

#### Назначение `data_check`

После каждой периодической серии empty-кадров снимается `data_count_per_step` кадров с тем же угловым положением, что и предыдущий data-кадр. Эти кадры нужны для:
- Проверки смещения образца (дрейфа) во время длительного эксперимента
- Коррекции данных при реконструкции

```
... [data pos=49] → [empty × 10] → [data_check pos=49] → [data pos=50] ...
                                    ↑ тот же угол
```

---

## Метаданные кадра

Каждый кадр в MongoDB (`frames` коллекция) содержит:

```json
{
  "_id": "ObjectId",
  "exp_id": "uuid-string",
  "type": "message",
  "frame": {
    "mode":   "data",
    "number": "00045",
    "image_data": {
      "timestamp": 1746619237.0,
      "datetime":  "07.05.2026 16:00:37",
      "exposure":  3000.0,
      "detector":  { "model": "MH110XC-KK-FA", "pixel_size": 0.00425 },
      "chip_temp": 25.3,
      "hous_temp": 28.1
    },
    "object": {
      "present":             true,
      "angle position":      16.2,
      "horizontal position": 0,
      "vertical position":   0
    },
    "shutter":     { "open": true },
    "X-ray source": { "voltage": 40.0, "current": 20.0 }
  }
}
```

В формате **v2** эти данные хранятся в типизированных массивах `timeline/`, а не как JSON для каждого кадра.

---

## HTTP API

| Метод | URL | Описание |
|---|---|---|
| POST | `/storage/experiments/create` | Создать новый эксперимент (всегда v2) |
| POST | `/storage/experiments/get` | Получить список экспериментов (фильтр в JSON) |
| POST | `/storage/experiments/finish` | Завершить эксперимент (финализация v2) |
| DELETE | `/storage/experiments/<id>` | Удалить эксперимент |
| POST | `/storage/frames/post` | Добавить кадр (multipart: data + file) |
| POST | `/storage/frames_info/get` | Получить метаданные кадров |
| GET | `/storage/experiments/<id>/frames/<frame_id>/png` | Получить PNG превью кадра |

### PNG превью

PNG генерируется асинхронно в фоновом потоке при получении каждого кадра:
- Downsampling 4x (например 4096→1024 по каждой оси)
- `scipy.ndimage.median_filter(size=3)` для шумоподавления
- Нормализация и colorbar через matplotlib
- Сохраняется в `data/experiments/<exp_id>/before_processing/png/<frame_id>.png`

> Из-за асинхронной генерации PNG может быть недоступен сразу после записи кадра.
> `rbtm-web` делает до 5 попыток с задержкой 3 сек при получении 404.

---

## Модули

### `hdf5_v2.py`

Модуль записи и чтения формата HDF5 v2.

**Ключевые функции:**
- `is_hdf5_v2(filepath)` — автодетекция версии
- `create_experiment_hdf5_v2(exp_id, params)` — создание файла
- `add_frame_v2(hdf5_path, frame, frame_info)` — добавление кадра
- `finalize_experiment_v2(hdf5_path)` — создание mapping индексов
- `get_experiment_info_v2(hdf5_path)` — чтение метаданных

### `pyframes.py`

Модуль добавления кадров с автодетекцией версии формата.
