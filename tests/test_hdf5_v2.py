"""
Тесты для storage/hdf5_v2.py.

Модуль загружается напрямую из файла (без импорта пакета storage), потому что
storage/__init__.py при импорте создаёт Flask-приложение, читает переменную
окружения YOURAPPLICATION_SETTINGS и подключается к MongoDB.
"""
import importlib.util
import pathlib

import h5py
import numpy as np
import pytest

_MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent / 'storage' / 'hdf5_v2.py'
_spec = importlib.util.spec_from_file_location('hdf5_v2', _MODULE_PATH)
hdf5_v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hdf5_v2)


def _advanced_params(series_length, data_total, empty_period=10, data_count_per_step=1):
    return {
        'specimen': 'test',
        'tags': '',
        'timestamp': 0.0,
        'datetime': '',
        'experiment parameters': {
            'advanced': True,
            'series_length': series_length,
            'empty_period': empty_period,
            'data_total': data_total,
            'data_angle_step': 1.0,
            'data_count_per_step': data_count_per_step,
        },
    }


def _simple_params(dark, empty, step_count, count_per_step=1):
    return {
        'specimen': 'test',
        'tags': '',
        'timestamp': 0.0,
        'datetime': '',
        'experiment parameters': {
            'advanced': False,
            'DARK': {'count': dark},
            'EMPTY': {'count': empty},
            'DATA': {'step count': step_count, 'count per step': count_per_step},
        },
    }


def _frame_info(number, mode, angle=None, **overrides):
    info = {
        'number': number,
        'mode': mode,
        'image_data': {'exposure': 100.0, 'timestamp': float(number), 'chip_temp': 25.0, 'hous_temp': 28.0},
        'object': {
            'angle position': float(number) if angle is None else angle,
            'present': mode != 'empty',
            'horizontal position': 0,
            'vertical position': 0,
        },
        'shutter': {'open': True},
        'X-ray source': {'voltage': 40.0, 'current': 20.0},
    }
    for path, value in overrides.items():
        group, key = path.split('.')
        info[group][key] = value
    return info


def _run_experiment(params, modes, frame_shape=(4, 5)):
    """Создаёт HDF5 v2 и последовательно добавляет кадры с заданными режимами."""
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.full(frame_shape, 7, dtype='uint16')
    for i, mode in enumerate(modes):
        idx, is_first = hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(i, mode))
        assert idx == i
        assert is_first == (i == 0)
    return hdf5_path


def test_advanced_short_experiment_seven_frames(tmp_path, monkeypatch):
    """Advanced, series_length=2, data_total=3: 7 кадров < chunk_size=10.

    Раньше h5py бросал «chunk shape must not be greater than data shape»
    на первом кадре, и роут /storage/frames/post отвечал 500.
    """
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=2, data_total=3)
    assert hdf5_v2.compute_total_frames(params) == 7

    modes = ['dark', 'dark', 'empty', 'empty', 'data', 'data', 'data']
    hdf5_path = _run_experiment(params, modes)

    with h5py.File(hdf5_path, 'r') as f:
        ds = f['images/all']
        assert ds.shape == (7, 4, 5)
        assert ds.chunks[0] <= 7
        assert ds.chunks[1:] == (4, 5)
        assert int(f.attrs['current_frame_index']) == 7
        assert list(f['timeline/modes'][:]) == [0, 0, 1, 1, 2, 2, 2]
        assert (ds[:] == 7).all()


def test_simple_short_experiment(tmp_path, monkeypatch):
    """Простой режим: 3 кадра < минимального chunk_size=10."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=1, empty=1, step_count=1)
    assert hdf5_v2.compute_total_frames(params) == 3

    hdf5_path = _run_experiment(params, ['dark', 'empty', 'data'])

    with h5py.File(hdf5_path, 'r') as f:
        ds = f['images/all']
        assert ds.shape == (3, 4, 5)
        assert 1 <= ds.chunks[0] <= 3


def test_single_frame_experiment(tmp_path, monkeypatch):
    """Граничный случай: эксперимент из одного кадра — chunk_size должен быть 1."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=1)
    assert hdf5_v2.compute_total_frames(params) == 1

    hdf5_path = _run_experiment(params, ['data'])

    with h5py.File(hdf5_path, 'r') as f:
        assert f['images/all'].chunks[0] == 1


def test_advanced_long_experiment_keeps_series_chunk(tmp_path, monkeypatch):
    """Длинный advanced-эксперимент: chunk_size по-прежнему равен series_length."""
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=12, data_total=20, empty_period=5)
    total = hdf5_v2.compute_total_frames(params)
    assert total > 12

    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')
    hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(0, 'dark'))

    with h5py.File(hdf5_path, 'r') as f:
        assert f['images/all'].chunks == (12, 4, 5)


def test_compute_total_frames_default_count_per_step():
    """drivers допускают отсутствие 'count per step' / 'data_count_per_step' — default 1."""
    simple = _simple_params(dark=1, empty=1, step_count=5)
    del simple['experiment parameters']['DATA']['count per step']
    assert hdf5_v2.compute_total_frames(simple) == 1 + 1 + 5

    advanced = _advanced_params(series_length=2, data_total=3)
    del advanced['experiment parameters']['data_count_per_step']
    assert hdf5_v2.compute_total_frames(advanced) == hdf5_v2.compute_total_frames(
        _advanced_params(series_length=2, data_total=3, data_count_per_step=1)
    )


def test_create_experiment_hdf5_v2_uses_detector_info(tmp_path, monkeypatch):
    """detector_info из документа эксперимента (top-level detector_model/pixel_size у drivers)
    должен попасть в metadata вместо дефолтных значений."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=1)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2(
        'exp-test', params, detector_info={'model': 'MH110XC-KK-FA', 'pixel_size': 0.00425}
    )

    with h5py.File(hdf5_path, 'r') as f:
        metadata = f['metadata']
        assert str(metadata['detector_model'][()], 'utf8') == 'MH110XC-KK-FA'
        assert float(metadata['pixel_size'][()]) == 0.00425


def test_none_metadata_values_do_not_crash_and_become_nan(tmp_path, monkeypatch):
    """None в числовых полях метаданных (drivers._safe_read) не должны ронять запись."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=2)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    info = _frame_info(0, 'data', **{'image_data.chip_temp': None, 'object.angle position': None})
    hdf5_v2.add_frame_v2(hdf5_path, frame, info)
    # второй кадр в норме, чтобы убедиться, что запись продолжается штатно
    hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(1, 'data'))

    with h5py.File(hdf5_path, 'r') as f:
        timeline = f['timeline']
        assert np.isnan(timeline['chip_temp'][0])
        assert np.isnan(timeline['angles'][0])
        assert not np.isnan(timeline['angles'][1])


def test_none_int_and_bool_fields_default_with_warning(tmp_path, monkeypatch, caplog):
    """None в int/bool-полях -> 0/False с предупреждением в лог."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=1)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    info = _frame_info(
        0, 'data',
        **{
            'object.horizontal position': None,
            'object.vertical position': None,
            'object.present': None,
            'shutter.open': None,
        }
    )
    with caplog.at_level('WARNING'):
        hdf5_v2.add_frame_v2(hdf5_path, frame, info)

    with h5py.File(hdf5_path, 'r') as f:
        timeline = f['timeline']
        assert timeline['horizontal_pos'][0] == 0
        assert timeline['vertical_pos'][0] == 0
        assert bool(timeline['object_present'][0]) is False
        assert bool(timeline['shutter_open'][0]) is False
    assert 'is None' in caplog.text


def test_horizontal_position_float_is_rounded_not_truncated(tmp_path, monkeypatch):
    """'horizontal position' у drivers может быть float (шаги + микрошаги) — округляем."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=1)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    info = _frame_info(0, 'data', **{'object.horizontal position': 12.6})
    hdf5_v2.add_frame_v2(hdf5_path, frame, info)

    with h5py.File(hdf5_path, 'r') as f:
        assert int(f['timeline/horizontal_pos'][0]) == 13  # round(), не int()/truncate


def test_first_frame_fills_source_and_detector_metadata(tmp_path, monkeypatch):
    """Первый кадр дозаполняет source_voltage/current и (если пусто) detector_model/pixel_size."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=0, empty=0, step_count=2)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    info = _frame_info(0, 'data')
    info['X-ray source'] = {'voltage': 42.0, 'current': 21.5}
    info['image_data']['detector'] = {'model': 'MH110XC-KK-FA', 'pixel_size': 0.00425}
    hdf5_v2.add_frame_v2(hdf5_path, frame, info)

    # Второй кадр с другим детектором не должен переопределить уже заполненные метаданные
    info2 = _frame_info(1, 'data')
    info2['X-ray source'] = {'voltage': 99.0, 'current': 99.0}
    info2['image_data']['detector'] = {'model': 'OTHER', 'pixel_size': 999.0}
    hdf5_v2.add_frame_v2(hdf5_path, frame, info2)

    with h5py.File(hdf5_path, 'r') as f:
        metadata = f['metadata']
        assert float(metadata['source_voltage'][()]) == 42.0
        assert float(metadata['source_current'][()]) == 21.5
        assert str(metadata['detector_model'][()], 'utf8') == 'MH110XC-KK-FA'
        assert float(metadata['pixel_size'][()]) == 0.00425


def test_segment_ids_sequence(tmp_path, monkeypatch):
    """Семантика segment_ids: -1 dark, 0 initial, k>=1 k-я periodic-вставка."""
    monkeypatch.chdir(tmp_path)
    modes = ['dark', 'dark', 'empty', 'empty', 'data', 'data',
             'empty', 'empty', 'data_check', 'data', 'data',
             'empty', 'empty', 'data_check', 'data']
    params = _advanced_params(series_length=2, data_total=5, empty_period=2)
    hdf5_path = _run_experiment(params, modes)

    with h5py.File(hdf5_path, 'r') as f:
        segment_ids = list(f['timeline/segment_ids'][:])

    assert segment_ids == [-1, -1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2]


def test_segment_ids_sequence_with_count_per_step_2(tmp_path, monkeypatch):
    """Та же семантика при data_count_per_step=2 (несколько data/data_check на шаг)."""
    monkeypatch.chdir(tmp_path)
    modes = [
        'dark', 'dark',
        'empty', 'empty',
        'data', 'data',            # step 1 (cps=2)
        'data', 'data',            # step 2 (cps=2)
        'empty', 'empty',          # вставка 1
        'data_check', 'data_check',
        'data', 'data',            # step 3
        'data', 'data',            # step 4
    ]
    params = _advanced_params(series_length=2, data_total=4, empty_period=2, data_count_per_step=2)
    hdf5_path = _run_experiment(params, modes)

    with h5py.File(hdf5_path, 'r') as f:
        segment_ids = list(f['timeline/segment_ids'][:])

    assert segment_ids == [-1, -1, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1]


def test_finalize_is_idempotent(tmp_path, monkeypatch):
    """Повторный вызов finalize_experiment_v2 не падает (не «name already exists»)."""
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=2, data_total=3, empty_period=10)
    hdf5_path = _run_experiment(params, ['dark', 'dark', 'empty', 'empty', 'data', 'data', 'data'])

    hdf5_v2.finalize_experiment_v2(hdf5_path)
    hdf5_v2.finalize_experiment_v2(hdf5_path)  # не должно упасть

    with h5py.File(hdf5_path, 'r') as f:
        assert list(f['mapping/dark_indices'][:]) == [0, 1]
        assert list(f['mapping/data_indices'][:]) == [4, 5, 6]


def test_finalize_checkpoint_pairs_one_per_periodic_series(tmp_path, monkeypatch):
    """Ровно одна checkpoint-пара на periodic-empty серию; data ищется по углу data_check."""
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=2, data_total=5, empty_period=2, data_count_per_step=1)
    assert hdf5_v2.compute_total_frames(params) == 15

    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    frames = [
        (0, 'dark', 0.0), (1, 'dark', 0.0),
        (2, 'empty', 0.0), (3, 'empty', 0.0),
        (4, 'data', 10.0), (5, 'data', 11.0),
        (6, 'empty', 0.0), (7, 'empty', 0.0),
        (8, 'data_check', 11.0),
        (9, 'data', 12.0), (10, 'data', 13.0),
        (11, 'empty', 0.0), (12, 'empty', 0.0),
        (13, 'data_check', 13.0),
        (14, 'data', 14.0),
    ]
    for number, mode, angle in frames:
        hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(number, mode, angle=angle))

    hdf5_v2.finalize_experiment_v2(hdf5_path)

    with h5py.File(hdf5_path, 'r') as f:
        checkpoint_data = list(f['mapping/checkpoint_data_indices'][:])
        checkpoint_dc = list(f['mapping/checkpoint_dc_indices'][:])
        angles = f['timeline/angles'][:]

    assert checkpoint_data == [5, 10]
    assert checkpoint_dc == [8, 13]
    for di, dci in zip(checkpoint_data, checkpoint_dc):
        assert angles[di] == angles[dci]

    # Повторный finalize идемпотентен и даёт тот же результат
    hdf5_v2.finalize_experiment_v2(hdf5_path)
    with h5py.File(hdf5_path, 'r') as f:
        assert list(f['mapping/checkpoint_data_indices'][:]) == [5, 10]
        assert list(f['mapping/checkpoint_dc_indices'][:]) == [8, 13]


def test_finalize_checkpoint_pair_with_count_per_step_2(tmp_path, monkeypatch):
    """cps=2: одна пара на checkpoint — первый dc ↔ последний data с тем же углом."""
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=2, data_total=4, empty_period=2, data_count_per_step=2)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.zeros((4, 5), dtype='uint16')

    frames = [
        (0, 'dark', 0.0), (1, 'dark', 0.0),
        (2, 'empty', 0.0), (3, 'empty', 0.0),
        (4, 'data', 10.0), (5, 'data', 10.0),     # step 1, cps=2
        (6, 'data', 11.0), (7, 'data', 11.0),     # step 2, cps=2
        (8, 'empty', 0.0), (9, 'empty', 0.0),     # periodic вставка
        (10, 'data_check', 11.0), (11, 'data_check', 11.0),
        (12, 'data', 12.0), (13, 'data', 12.0),   # step 3
        (14, 'data', 13.0), (15, 'data', 13.0),   # step 4
    ]
    for number, mode, angle in frames:
        hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(number, mode, angle=angle))

    hdf5_v2.finalize_experiment_v2(hdf5_path)

    with h5py.File(hdf5_path, 'r') as f:
        checkpoint_data = list(f['mapping/checkpoint_data_indices'][:])
        checkpoint_dc = list(f['mapping/checkpoint_dc_indices'][:])

    # первый dc checkpoint'а (index 10) ↔ последний data с тем же углом до него (index 7)
    assert checkpoint_dc == [10]
    assert checkpoint_data == [7]


def test_duplicate_frame_retry_is_idempotent(tmp_path, monkeypatch):
    """Повтор POST того же кадра (ответ потерялся после успешной записи) не пишет второй кадр."""
    monkeypatch.chdir(tmp_path)
    params = _simple_params(dark=1, empty=1, step_count=1)
    hdf5_path = _run_experiment(params, ['dark', 'empty'])

    frame = np.full((4, 5), 9, dtype='uint16')
    idx, is_first = hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(1, 'empty'))
    assert (idx, is_first) == (1, False)

    with h5py.File(hdf5_path, 'r') as f:
        assert int(f.attrs['current_frame_index']) == 2
        assert list(f['timeline/modes'][:]) == [0, 1]

    # Следующий, ещё не записанный кадр принимается как обычно
    idx, _ = hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(2, 'data'))
    assert idx == 2


def test_file_not_bloated_by_per_frame_rewrites(tmp_path, monkeypatch):
    """Файл не раздувается: каждый кадр переписывает сжатый чанк (файл открывается на кадр), и если между записями
    в конец файла попадает что-то ещё (раньше — attrs last_mode строкой переменной длины, она живёт в глобальной
    куче), старые версии чанка остаются дырами — скан dc5548a3 от 01.10.2026: 40 ГБ при 7,3 ГБ кадров."""
    monkeypatch.chdir(tmp_path)
    modes = ['dark'] * 2 + ['empty'] * 2 + ['data'] * 10
    for k in range(2):                                                # вставка после каждых 10 data, кроме последних
        modes += ['empty'] * 2 + ['data_check'] + ['data'] * 10
    params = _advanced_params(series_length=2, data_total=30, empty_period=10)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    rng = np.random.default_rng(0)
    for i, mode in enumerate(modes):
        frame = rng.poisson(3000, (96, 128)).astype('uint16')          # шум — сжимается слабо, как реальные кадры
        hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(i, mode))
    with h5py.File(hdf5_path, 'r') as f:
        images = f['images/all'].id.get_storage_size()
        assert list(f['timeline/segment_ids'][:])[:6] == [-1, -1, 0, 0, 0, 0]
    size = pathlib.Path(hdf5_path).stat().st_size
    assert size <= 1.3 * images + (1 << 20), 'файл {} байт при {} байт кадров'.format(size, images)


def test_segment_continues_in_file_started_by_previous_version(tmp_path, monkeypatch):
    """Эксперимент, начатый версией со строковым attrs['last_mode'] (шёл во время выкатки), продолжается: режим
    предыдущего кадра берётся из строки, новые кадры пишут целый код, строка больше не обновляется."""
    monkeypatch.chdir(tmp_path)
    params = _advanced_params(series_length=2, data_total=4, empty_period=2)
    hdf5_path = hdf5_v2.create_experiment_hdf5_v2('exp-test', params)
    frame = np.full((4, 5), 7, dtype='uint16')
    modes = ['dark', 'dark', 'empty', 'empty', 'data', 'data']
    for i, mode in enumerate(modes):
        hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(i, mode))
    with h5py.File(hdf5_path, 'r+') as f:                         # как файл старой версии
        del f.attrs[hdf5_v2.LAST_MODE_ATTR]
        f.attrs['last_mode'] = 'data'
    for i, mode in enumerate(['empty', 'empty', 'data_check', 'data', 'data'], start=len(modes)):
        hdf5_v2.add_frame_v2(hdf5_path, frame, _frame_info(i, mode))
    with h5py.File(hdf5_path, 'r') as f:
        assert list(f['timeline/segment_ids'][:]) == [-1, -1, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        assert int(f.attrs[hdf5_v2.LAST_MODE_ATTR]) == hdf5_v2.FRAME_MODES['data']
        assert f.attrs['last_mode'] == 'data'
