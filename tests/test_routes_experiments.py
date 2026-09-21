"""
Тесты для storage/routes/experiments.py (роут /storage/experiments/finish).

Как и test_routes_storage.py, использует mongomock вместо реального MongoDB.
"""
import json
import pathlib
import sys

import pytest

mongomock = pytest.importorskip('mongomock')

_CONF_PATH = str(pathlib.Path(__file__).resolve().parent.parent / 'storage' / 'conf_dev.py')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('YOURAPPLICATION_SETTINGS', _CONF_PATH)

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


def _create_experiment(client, exp_id, dark=0, empty=0, step_count=1):
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


def _finish(client, exp_id, message=None, exception_message=None, error=None):
    body = {'exp_id': exp_id, 'type': 'message'}
    if message is not None:
        body['message'] = message
    if exception_message is not None:
        body['exception message'] = exception_message
    if error is not None:
        body['error'] = error
    return client.post('/storage/experiments/finish', data=json.dumps(body), content_type='application/json')


def test_finish_success_sets_finished_and_finalizes(client):
    test_client, db = client
    exp_id = 'exp-finish-ok'
    _create_experiment(test_client, exp_id, dark=1, empty=0, step_count=0)

    resp = _finish(test_client, exp_id, message='Experiment was finished successfully')
    assert resp.status_code == 200

    doc = db['experiments'].find_one({'_id': exp_id})
    assert doc['finished'] is True
    assert 'stopped_with_error' not in doc


def test_finish_error_message_sets_stopped_with_error_and_still_finalizes(client):
    """Не-успешное сообщение о завершении: finished не ставится, но HDF5 всё равно финализируется
    (mapping нужен reader'у и для прерванных экспериментов)."""
    test_client, db = client
    exp_id = 'exp-finish-error'
    _create_experiment(test_client, exp_id, dark=1, empty=0, step_count=0)

    resp = _finish(test_client, exp_id, message='Experiment was stopped', exception_message='boom', error='details')
    assert resp.status_code == 200

    doc = db['experiments'].find_one({'_id': exp_id})
    assert doc.get('finished') in (False, None)
    assert doc['stopped_with_error'] == 'boom'

    import h5py
    import os
    hdf5_path = os.path.join('data', 'experiments', exp_id, 'before_processing', f'{exp_id}.h5')
    with h5py.File(hdf5_path, 'r') as f:
        assert 'mapping' in f  # финализация прошла несмотря на не-успешное сообщение


def test_finish_unknown_experiment_returns_404(client):
    test_client, db = client
    resp = _finish(test_client, 'does-not-exist', message='Experiment was finished successfully')
    assert resp.status_code == 404
    assert 'error' in resp.get_json()
