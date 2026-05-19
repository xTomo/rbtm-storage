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
│   ├── <exp_id>.h5          # HDF5 с кадрами (группы по типу)
│   └── png/
│       └── <frame_id>.png   # PNG превью для каждого кадра
└── after_processing/
```

### Структура HDF5-файла

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

> **Примечание**: группа `data_check` добавлена для поддержки продвинутого режима эксперимента.

#### Атрибут `exp_info` в HDF5

Атрибут `exp_info` в корне HDF5-файла — это полный JSON-документ эксперимента из MongoDB, сериализованный через `bson.json_util.dumps`. Параметры эксперимента **вложены** в ключ `"experiment parameters"`:

```json
{
  "_id": "uuid-string",
  "specimen": "Название образца",
  "datetime": "...",
  "timestamp": 1746619237.0,
  "experiment parameters": {
    "advanced": true,
    "series_length": 10,
    "empty_period": 50,
    "data_total": 500
  }
}
```

> ⚠️ **Ловушка**: `exp_info['series_length']` не существует — нужно `exp_info['experiment parameters']['series_length']`.
> Код реконструкции (`tomotools4._read_series_length_from_hdf5`) читает правильно начиная с commit `825536e`.

#### Ключи датасетов (frame_numbers)

Датасеты внутри групп именуются строковым представлением глобального `frame_num` с zero-padding:
- `"000020"`, `"000021"`, ... — порядковый номер кадра в рамках всего эксперимента
- Порядок: dark → initial_empty → data[0] → ... → periodic_empty → data_check → data[N] → ...
- Для разделения initial vs periodic empty кадров используют сравнение `frame_number` с `frame_numbers` первых data-кадров

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

#### Чем отличается продвинутый режим

| Аспект | Простой | Продвинутый |
|---|---|---|
| Экспозиции | Раздельные для dark/empty/data | Единая для всех |
| empty-серии | Только в начале | В начале + периодически каждые N позиций |
| `data_check` кадры | Нет | Да — после каждой периодической empty-серии |
| HDF5-группы | dark, empty, data | dark, empty, data, data_check |

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

---

## HTTP API

| Метод | URL | Описание |
|---|---|---|
| POST | `/storage/experiments/create` | Создать новый эксперимент |
| POST | `/storage/experiments/get` | Получить список экспериментов (фильтр в JSON) |
| POST | `/storage/experiments/finish` | Завершить эксперимент |
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
