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


def _frame_info(number, mode):
    return {
        'number': number,
        'mode': mode,
        'image_data': {'exposure': 100.0, 'timestamp': float(number)},
        'object': {'angle position': float(number), 'present': mode != 'empty'},
        'shutter': {'open': True},
    }


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
