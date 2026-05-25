"""
hdf5_v2.py — Модуль записи экспериментов в формате HDF5 v2.

Формат v2 использует единую временную ось (timeline) для всех кадров
и централизованное хранение метаданных эксперимента.

Структура HDF5 v2:
─────────────────────────────────────────────────────────────────────────────
<exp_id>.h5
├── attrs
│   ├── format_version       # str: "v2"
│   └── created_at           # str: ISO datetime
│
├── metadata/                # Константы эксперимента
│   ├── experiment_id        # str
│   ├── specimen             # str
│   ├── tags                 # str
│   ├── timestamp            # float64
│   ├── datetime             # str
│   ├── is_advanced          # bool
│   ├── series_length        # int32 (если advanced)
│   ├── empty_period         # int32 (если advanced)
│   ├── data_total           # int32 (если advanced)
│   ├── data_angle_step      # float32 (если advanced)
│   ├── data_count_per_step  # int32 (если advanced)
│   ├── detector_model       # str
│   ├── pixel_size           # float32 (мм)
│   ├── source_voltage       # float32 (кВ)
│   └── source_current       # float32 (мкА)
│
├── timeline/                # Типизированные массивы, shape (N_total,)
│   ├── frame_numbers        # int64   — глобальные номера кадров
│   ├── modes                # uint8   — 0=dark, 1=empty, 2=data, 3=data_check
│   ├── angles               # float32 — углы (градусы)
│   ├── exposures            # float32 — экспозиции (мс)
│   ├── timestamps           # float64 — UNIX time
│   ├── object_present       # bool    — образец в пучке
│   ├── shutter_open         # bool    — затвор открыт
│   ├── chip_temp            # float32 — температура чипа детектора
│   ├── hous_temp            # float32 — температура корпуса детектора
│   ├── horizontal_pos       # int32   — горизонтальная позиция
│   ├── vertical_pos         # int32   — вертикальная позиция
│   └── segment_ids          # int32   — номер сегмента (-1=dark, 0=initial, 1+=periodic)
│
├── images/                  # Бинарные данные кадров
│   └── all                  # uint16[N_total, H, W], chunked, gzip
│
└── mapping/                 # Индексы для быстрого доступа (заполняется после эксперимента)
    ├── dark_indices         # int32[N_dark]   — индексы в timeline для dark
    ├── empty_indices        # int32[N_empty]  — индексы в timeline для empty
    ├── data_indices         # int32[N_data]   — индексы в timeline для data
    ├── data_check_indices   # int32[N_dc]     — индексы в timeline для data_check
    ├── checkpoint_data_indices   # int32[K] — индексы data-кадров ДО checkpoint
    └── checkpoint_dc_indices     # int32[K] — индексы data_check-кадров ПОСЛЕ checkpoint
─────────────────────────────────────────────────────────────────────────────
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import h5py
import numpy as np
import portalocker

logger = logging.getLogger(__name__)

# Enum для режимов кадров
FRAME_MODES = {
    'dark': 0,
    'empty': 1,
    'data': 2,
    'data_check': 3,
}

MODE_NAMES = {v: k for k, v in FRAME_MODES.items()}


def is_hdf5_v2(filepath: str) -> bool:
    """
    Определяет версию HDF5-файла.
    
    Returns:
        True если файл формата v2 (имеет группу /timeline и format_version='v2'),
        False иначе.
    """
    try:
        with h5py.File(filepath, 'r') as f:
            if 'timeline' not in f:
                return False
            # Дополнительная проверка версии в metadata
            if 'metadata' in f and 'format_version' in f['metadata']:
                version = str(f['metadata']['format_version'][()], 'utf8')
                return version == 'v2'
            return True
    except Exception:
        return False


def compute_total_frames(params: Dict[str, Any]) -> int:
    """
    Вычисляет общее количество кадров в эксперименте.
    
    Args:
        params: Параметры эксперимента из MongoDB
        
    Returns:
        Общее число кадров
    """
    is_advanced = params.get('experiment parameters', {}).get('advanced', False)
    
    if not is_advanced:
        # Простой режим
        exp_params = params['experiment parameters']
        dark_count = exp_params['DARK']['count']
        empty_count = exp_params['EMPTY']['count']
        data_count = exp_params['DATA']['step count'] * exp_params['DATA']['count per step']
        return dark_count + empty_count + data_count
    else:
        # Продвинутый режим
        adv_params = params['experiment parameters']
        series_length = adv_params['series_length']
        data_total = adv_params['data_total']
        data_count_per_step = adv_params['data_count_per_step']
        empty_period = adv_params['empty_period']
        
        num_empty_inserts = (data_total - 1) // empty_period
        
        total_frames = (
            series_length                               # dark
            + series_length                             # начальная empty
            + data_total * data_count_per_step          # data
            + num_empty_inserts * series_length         # периодические empty
            + num_empty_inserts * data_count_per_step   # data_check
        )
        return total_frames


def create_experiment_hdf5_v2(
    experiment_id: str,
    params: Dict[str, Any],
    detector_info: Optional[Dict[str, Any]] = None,
    source_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Создаёт HDF5-файл формата v2 для нового эксперимента.
    
    Args:
        experiment_id: UUID эксперимента
        params: Параметры эксперимента из MongoDB
        detector_info: Информация о детекторе (model, pixel_size)
        source_info: Информация об источнике (voltage, current)
        
    Returns:
        Путь к созданному HDF5-файлу
    """
    base_path = os.path.join('data', 'experiments', str(experiment_id))
    before_processing_path = os.path.join(base_path, 'before_processing')
    os.makedirs(before_processing_path, exist_ok=True)
    
    hdf5_path = os.path.join(before_processing_path, f'{experiment_id}.h5')
    
    # Вычисляем общее число кадров
    total_frames = compute_total_frames(params)
    
    exp_params = params.get('experiment parameters', {})
    is_advanced = exp_params.get('advanced', False)
    
    # Получаем детектор и источник
    detector_model = ''
    pixel_size = 4.25e-3  # мм, default
    if detector_info:
        detector_model = detector_info.get('model', '')
        pixel_size = float(detector_info.get('pixel_size', 4.25e-3))
    
    source_voltage = 0.0
    source_current = 0.0
    if source_info:
        source_voltage = float(source_info.get('voltage', 0.0))
        source_current = float(source_info.get('current', 0.0))
    
    with h5py.File(hdf5_path, 'w') as f:
        # Атрибуты файла
        f.attrs['format_version'] = 'v2'
        f.attrs['created_at'] = datetime.now().isoformat()
        
        # Metadata
        metadata = f.create_group('metadata')
        metadata.create_dataset('format_version', data='v2')  # Явная версия в metadata
        metadata.create_dataset('experiment_id', data=str(experiment_id).encode('utf8'))
        metadata.create_dataset('specimen', data=params.get('specimen', '').encode('utf8'))
        metadata.create_dataset('tags', data=params.get('tags', '').encode('utf8'))
        metadata.create_dataset('timestamp', data=params.get('timestamp', 0.0))
        metadata.create_dataset('datetime', data=params.get('datetime', '').encode('utf8'))
        metadata.create_dataset('is_advanced', data=is_advanced)
        metadata.create_dataset('detector_model', data=detector_model.encode('utf8'))
        metadata.create_dataset('pixel_size', data=pixel_size)
        metadata.create_dataset('source_voltage', data=source_voltage)
        metadata.create_dataset('source_current', data=source_current)
        
        # Advanced параметры
        if is_advanced:
            metadata.create_dataset('series_length', data=exp_params['series_length'])
            metadata.create_dataset('empty_period', data=exp_params['empty_period'])
            metadata.create_dataset('data_total', data=exp_params['data_total'])
            metadata.create_dataset('data_angle_step', data=exp_params['data_angle_step'])
            metadata.create_dataset('data_count_per_step', data=exp_params['data_count_per_step'])
        else:
            metadata.create_dataset('series_length', data=0)
            metadata.create_dataset('empty_period', data=0)
            metadata.create_dataset('data_total', data=0)
            metadata.create_dataset('data_angle_step', data=0.0)
            metadata.create_dataset('data_count_per_step', data=0)
        
        # Сохраняем также полный JSON для совместимости
        exp_info_json = json.dumps(params)
        f.attrs['exp_info_json'] = exp_info_json
        
        # Timeline — создаём resizable датасеты
        timeline = f.create_group('timeline')
        
        timeline_datasets = {
            'frame_numbers': ('int64', 0),
            'modes': ('uint8', 0),
            'angles': ('float32', 0.0),
            'exposures': ('float32', 0.0),
            'timestamps': ('float64', 0.0),
            'object_present': ('bool', False),
            'shutter_open': ('bool', False),
            'chip_temp': ('float32', 0.0),
            'hous_temp': ('float32', 0.0),
            'horizontal_pos': ('int32', 0),
            'vertical_pos': ('int32', 0),
            'segment_ids': ('int32', -1),
        }
        
        for name, (dtype, fill_value) in timeline_datasets.items():
            timeline.create_dataset(
                name,
                shape=(0,),
                maxshape=(total_frames,),
                dtype=dtype,
                chunks=True,
                fillvalue=fill_value
            )
        
        # Images — будет создан при получении первого кадра
        # (когда узнаём размеры кадра)
        f.attrs['images_initialized'] = False
        f.attrs['total_frames'] = total_frames
        f.attrs['current_frame_index'] = 0
    
    logger.info(f'Created HDF5 v2 file: {hdf5_path} (total_frames={total_frames})')
    return hdf5_path


def add_frame_v2(
    hdf5_path: str,
    frame: np.ndarray,
    frame_info: Dict[str, Any],
    lock_timeout: int = 60,
) -> Tuple[int, bool]:
    """
    Добавляет кадр в HDF5-файл формата v2.
    
    Args:
        hdf5_path: Путь к HDF5-файлу
        frame: Массив кадра (H, W), dtype uint16
        frame_info: Метаданные кадра (структура из drivers)
        lock_timeout: Таймаут блокировки файла (сек)
        
    Returns:
        (frame_index, is_first_frame) — индекс кадра в timeline, был ли первым
    """
    lock_path = hdf5_path + '.lock'
    
    with portalocker.Lock(lock_path, timeout=lock_timeout):
        with h5py.File(hdf5_path, 'r+') as f:
            # Проверяем версию
            if not is_hdf5_v2(hdf5_path):
                raise ValueError(f'File {hdf5_path} is not HDF5 v2 format')
            
            # Получаем текущий индекс
            current_idx = int(f.attrs['current_frame_index'])
            is_first_frame = (current_idx == 0)
            
            # Инициализируем images при первом кадре
            if not f.attrs.get('images_initialized', False):
                H, W = frame.shape
                total_frames = int(f.attrs['total_frames'])
                
                # Определяем chunk size
                is_advanced = bool(f['metadata/is_advanced'][()])
                if is_advanced:
                    series_length = int(f['metadata/series_length'][()])
                    chunk_size = max(series_length, 10)
                else:
                    chunk_size = min(100, max(total_frames // 10, 10))
                
                images_group = f.create_group('images')
                images_group.create_dataset(
                    'all',
                    shape=(total_frames, H, W),
                    dtype='uint16',
                    chunks=(chunk_size, H, W),
                    compression='gzip',
                    compression_opts=4
                )
                f.attrs['images_initialized'] = True
                logger.info(f'Initialized images/all with shape ({total_frames}, {H}, {W}), chunk_size={chunk_size}')
            
            # Извлекаем данные из frame_info
            mode_str = frame_info.get('mode', 'data')
            mode_code = FRAME_MODES.get(mode_str, 2)
            
            image_data = frame_info.get('image_data', {})
            obj_info = frame_info.get('object', {})
            shutter_info = frame_info.get('shutter', {})
            source_info = frame_info.get('X-ray source', {})
            
            # Определяем segment_id
            segment_id = _compute_segment_id(f, frame_info, current_idx)
            
            # Записываем в timeline
            timeline = f['timeline']
            
            # Расширяем timeline на 1 элемент
            for name in timeline.keys():
                ds = timeline[name]
                ds.resize((current_idx + 1,), axis=0)
                ds[current_idx] = {
                    'frame_numbers': int(frame_info.get('number', current_idx)),
                    'modes': mode_code,
                    'angles': float(obj_info.get('angle position', 0.0)),
                    'exposures': float(image_data.get('exposure', 0.0)),
                    'timestamps': float(image_data.get('timestamp', 0.0)),
                    'object_present': bool(obj_info.get('present', True)),
                    'shutter_open': bool(shutter_info.get('open', False)),
                    'chip_temp': float(image_data.get('chip_temp', 0.0)),
                    'hous_temp': float(image_data.get('hous_temp', 0.0)),
                    'horizontal_pos': int(obj_info.get('horizontal position', 0)),
                    'vertical_pos': int(obj_info.get('vertical position', 0)),
                    'segment_ids': segment_id,
                }[name]
            
            # Записываем кадр в images
            f['images/all'][current_idx] = frame
            
            # Обновляем счётчик
            f.attrs['current_frame_index'] = current_idx + 1
            
            return current_idx, is_first_frame


def _compute_segment_id(f: h5py.File, frame_info: Dict[str, Any], current_idx: int) -> int:
    """
    Вычисляет segment_id для кадра.
    
    Сегменты:
      - -1: dark кадры
      - 0: initial empty и data до первой periodic вставки
      - 1+: data после periodic вставки k
    
    Args:
        f: HDF5 файл (открыт для чтения)
        frame_info: Метаданные кадра
        current_idx: Текущий индекс в timeline
        
    Returns:
        segment_id (int)
    """
    mode_str = frame_info.get('mode', 'data')
    
    if mode_str == 'dark':
        return -1
    
    if mode_str == 'empty':
        # Все empty — сегмент 0 (initial)
        return 0
    
    if mode_str == 'data_check':
        # data_check относится к предыдущему checkpoint
        # Находим номер checkpoint по количеству data_check в timeline
        timeline = f['timeline']
        if current_idx == 0:
            return 0
        
        modes_so_far = timeline['modes'][:current_idx]
        num_dc_so_far = int(np.sum(modes_so_far == FRAME_MODES['data_check']))
        return num_dc_so_far + 1  # segment = checkpoint + 1
    
    if mode_str == 'data':
        # data — сегмент зависит от количества periodic вставок до этого кадра
        timeline = f['timeline']
        if current_idx == 0:
            return 0
        
        modes_so_far = timeline['modes'][:current_idx]
        # Считаем количество completed periodic empty серий
        # Это число переходов empty после initial
        empty_indices = np.where(modes_so_far == FRAME_MODES['empty'])[0]
        
        if len(empty_indices) == 0:
            return 0
        
        # Начальная empty серия идёт сразу после dark
        # periodic empty серии идут после data
        # Считаем periodic как empty после первого data
        data_indices = np.where(modes_so_far == FRAME_MODES['data'])[0]
        if len(data_indices) == 0:
            return 0  # ещё не было data
        
        first_data_idx = data_indices[0]
        periodic_empty_count = int(np.sum(empty_indices > first_data_idx))
        
        return periodic_empty_count
    
    return 0


def finalize_experiment_v2(hdf5_path: str, lock_timeout: int = 60) -> None:
    """
    Завершает эксперимент: создаёт mapping индексы.
    
    Args:
        hdf5_path: Путь к HDF5-файлу
        lock_timeout: Таймаут блокировки файла
    """
    lock_path = hdf5_path + '.lock'
    
    with portalocker.Lock(lock_path, timeout=lock_timeout):
        with h5py.File(hdf5_path, 'r+') as f:
            if not is_hdf5_v2(hdf5_path):
                raise ValueError(f'File {hdf5_path} is not HDF5 v2 format')
            
            timeline = f['timeline']
            modes = timeline['modes'][:]
            frame_numbers = timeline['frame_numbers'][:]
            angles = timeline['angles'][:]
            
            # Создаём mapping группу
            if 'mapping' not in f:
                mapping = f.create_group('mapping')
            else:
                mapping = f['mapping']
            
            # Индексы по типам
            for mode_name, mode_code in FRAME_MODES.items():
                indices = np.where(modes == mode_code)[0].astype('int32')
                if mode_name in mapping:
                    del mapping[mode_name]
                mapping.create_dataset(f'{mode_name}_indices', data=indices)
            
            # checkpoint индексы для advanced
            is_advanced = bool(f['metadata/is_advanced'][()])
            if is_advanced:
                periodic_empty_fnums = []
                data_check_indices = []
                checkpoint_data_indices = []
                
                # Находим periodic empty серии и соответствующие data_check
                empty_indices = mapping['empty_indices'][:]
                data_indices = mapping['data_indices'][:]
                dc_indices = mapping['data_check_indices'][:]
                
                if len(empty_indices) > 0 and len(data_indices) > 0:
                    # initial empty — это первые series_length empty
                    series_length = int(f['metadata/series_length'][()])
                    periodic_empty_start = series_length
                    
                    # periodic empty начинаются после initial
                    if periodic_empty_start < len(empty_indices):
                        periodic_empty_idxs = empty_indices[periodic_empty_start:]
                        
                        # Для каждого periodic empty находим соответствующий data_check
                        for i, pe_idx in enumerate(periodic_empty_idxs):
                            pe_fn = frame_numbers[pe_idx]
                            
                            # data_check с frame_number > periodic empty
                            dc_mask = frame_numbers[dc_indices] > pe_fn
                            dc_candidates = dc_indices[dc_mask]
                            
                            if len(dc_candidates) > 0:
                                dc_idx = dc_candidates[0]
                                data_check_indices.append(dc_idx)
                                
                                # data кадр перед periodic empty (при том же угле)
                                pe_angle = angles[pe_idx]
                                data_before_mask = (data_indices < pe_idx) & (np.abs(angles[data_indices] - pe_angle) < 0.01)
                                data_before = data_indices[data_before_mask]
                                
                                if len(data_before) > 0:
                                    checkpoint_data_indices.append(data_before[-1])
                                else:
                                    checkpoint_data_indices.append(-1)
                            else:
                                data_check_indices.append(-1)
                                checkpoint_data_indices.append(-1)
                
                if len(data_check_indices) > 0:
                    mapping.create_dataset('checkpoint_data_indices', 
                                          data=np.array(checkpoint_data_indices, dtype='int32'))
                    mapping.create_dataset('checkpoint_dc_indices', 
                                          data=np.array(data_check_indices, dtype='int32'))
            
            logger.info(f'Finalized experiment HDF5 v2: {hdf5_path}')


def get_experiment_info_v2(hdf5_path: str) -> Dict[str, Any]:
    """
    Читает метаданные эксперимента из HDF5 v2.
    
    Args:
        hdf5_path: Путь к HDF5-файлу
        
    Returns:
        Dict с метаданными
    """
    with h5py.File(hdf5_path, 'r') as f:
        if not is_hdf5_v2(hdf5_path):
            raise ValueError(f'File {hdf5_path} is not HDF5 v2 format')
        
        metadata = f['metadata']
        
        info = {
            'format_version': str(metadata['format_version'][()], 'utf8'),
            'experiment_id': str(metadata['experiment_id'][()], 'utf8'),
            'specimen': str(metadata['specimen'][()], 'utf8'),
            'tags': str(metadata['tags'][()], 'utf8'),
            'timestamp': float(metadata['timestamp'][()]),
            'datetime': str(metadata['datetime'][()], 'utf8'),
            'is_advanced': bool(metadata['is_advanced'][()]),
            'detector_model': str(metadata['detector_model'][()], 'utf8'),
            'pixel_size': float(metadata['pixel_size'][()]),
            'source_voltage': float(metadata['source_voltage'][()]),
            'source_current': float(metadata['source_current'][()]),
        }
        
        if info['is_advanced']:
            info['series_length'] = int(metadata['series_length'][()])
            info['empty_period'] = int(metadata['empty_period'][()])
            info['data_total'] = int(metadata['data_total'][()])
            info['data_angle_step'] = float(metadata['data_angle_step'][()])
            info['data_count_per_step'] = int(metadata['data_count_per_step'][()])
        
        # Статистика по кадрам
        timeline = f['timeline']
        modes = timeline['modes'][:]
        
        info['total_frames'] = len(modes)
        info['dark_count'] = int(np.sum(modes == FRAME_MODES['dark']))
        info['empty_count'] = int(np.sum(modes == FRAME_MODES['empty']))
        info['data_count'] = int(np.sum(modes == FRAME_MODES['data']))
        info['data_check_count'] = int(np.sum(modes == FRAME_MODES['data_check']))
        
        return info
