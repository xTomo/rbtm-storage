"""
Тесты для storage/routes/storage.py (роут /storage/frames/post).

В отличие от test_hdf5_v2.py, здесь нужен полноценный Flask-пакет storage
(app, blueprints), поэтому storage.db.get_db подменяется на mongomock —
реальный MongoDB не требуется.
"""
import io
import json
import pathlib
import sys

import numpy as np
import pytest

mongomock = pytest.importorskip('mongomock')

_CONF_PATH = str(pathlib.Path(__file__).resolve().parent.parent / 'storage' / 'conf_dev.py')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('YOURAPPLICATION_SETTINGS', _CONF_PATH)

    # storage/__init__.py создаёт Flask app и регистрирует blueprints при импорте —
    # перезагружаем пакет на каждый тест, чтобы не задваивать blueprints между тестами.
    for mod_name in list(sys.modules):
        if mod_name == 'storage' or mod_name.startswith('storage.'):
            del sys.modules[mod_name]

    import storage as storage_pkg
    from storage.routes import storage as storage_routes_mod
    from storage.routes import experiments as experiments_routes_mod

    mongo_client = mongomock.MongoClient()
    db = mongo_client['robotom']
    monkeypatch.setattr(storage_routes_mod, 'get_db', lambda: db)
    monkeypatch.setattr(experiments_routes_mod, 'get_db', lambda: db)

    storage_pkg.app.config['TESTING'] = True
    with storage_pkg.app.test_client() as test_client:
        yield test_client, db


def _create_experiment(client, exp_id, dark=0, empty=0, step_count=2):
    payload = {
        'exp_id': exp_id,
        'specimen': 'test',
        'tags': '',
        'timestamp': 0.0,
        'datetime': '',
        'experiment parameters': {
            'advanced': False,
            'DARK': {'count': dark},
            'EMPTY': {'count': empty},
            'DATA': {'step count': step_count, 'count per step': 1},
        },
    }
    resp = client.post('/storage/experiments/create', data=json.dumps(payload), content_type='application/json')
    assert resp.status_code == 200
    assert resp.get_json()['result'] == 'success'


def _post_frame(client, exp_id, number, mode='data', angle=0.0):
    frame_json = {
        'exp_id': exp_id,
        'type': 'message',
        'frame': {
            'mode': mode,
            'number': str(number).zfill(5),
            'image_data': {
                'timestamp': float(number), 'datetime': '', 'exposure': 100.0,
                'detector': {'model': 'test-det', 'pixel_size': 0.001},
                'chip_temp': 25.0, 'hous_temp': 28.0,
            },
            'object': {'present': True, 'angle position': angle, 'horizontal position': 0, 'vertical position': 0},
            'shutter': {'open': True},
            'X-ray source': {'voltage': 40.0, 'current': 20.0},
        },
    }
    frame = np.zeros((4, 5), dtype='uint16')
    buf = io.BytesIO()
    np.savez(buf, frame_data=frame)
    buf.seek(0)

    return client.post(
        '/storage/frames/post',
        data={'data': json.dumps(frame_json), 'file': (buf, 'frame.npz')},
        content_type='multipart/form-data',
    )


def test_new_frame_writes_hdf5_and_mongo_doc(client):
    test_client, db = client
    exp_id = 'exp-route-test'
    _create_experiment(test_client, exp_id, dark=0, empty=0, step_count=2)

    resp = _post_frame(test_client, exp_id, 0, mode='data', angle=1.0)
    assert resp.status_code == 200
    assert resp.get_json()['result'] == 'success'

    docs = list(db['frames'].find({'exp_id': exp_id}))
    assert len(docs) == 1
    assert docs[0]['frame']['number'] == '00000'


def test_new_frame_retry_is_idempotent_in_mongo(client):
    """Повторная отправка того же кадра (как при ретрае drivers после 500) не плодит дубли в Mongo.

    HDF5-запись не дедуплицируется по frame.number (это отдельная, не решаемая
    здесь проблема — drivers ретраят только при реальном 500), но
    Mongo-документ на (exp_id, frame.number) остаётся ровно один благодаря upsert.
    """
    test_client, db = client
    exp_id = 'exp-route-retry'
    _create_experiment(test_client, exp_id, dark=0, empty=0, step_count=2)

    resp1 = _post_frame(test_client, exp_id, 0, mode='data', angle=1.0)
    assert resp1.status_code == 200

    # тот же frame.number — имитация ретрая
    resp2 = _post_frame(test_client, exp_id, 0, mode='data', angle=1.0)
    assert resp2.status_code == 200

    docs = list(db['frames'].find({'exp_id': exp_id, 'frame.number': '00000'}))
    assert len(docs) == 1  # апсерт не создал дубль в Mongo


def test_new_frame_hdf5_error_returns_500_and_skips_mongo_insert(client):
    """Если HDF5-запись падает (например, эксперимент уже заполнен), Mongo не получает документ."""
    test_client, db = client
    exp_id = 'exp-route-full'
    _create_experiment(test_client, exp_id, dark=0, empty=0, step_count=1)  # total_frames=1

    resp1 = _post_frame(test_client, exp_id, 0, mode='data', angle=1.0)
    assert resp1.status_code == 200

    # второй кадр превышает total_frames=1
    resp2 = _post_frame(test_client, exp_id, 1, mode='data', angle=2.0)
    assert resp2.status_code == 500
    assert 'error' in resp2.get_json()

    docs = list(db['frames'].find({'exp_id': exp_id}))
    assert len(docs) == 1  # второй (неудавшийся) кадр не попал в Mongo
