"""
Тесты для storage/routes/errors.py: 400/404 не должны логировать traceback,
только 500 (см. storage/routes/errors.py).
"""
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
        yield test_client


def test_404_returns_json_without_traceback(client, caplog):
    resp = client.get('/storage/no-such-route')
    assert resp.status_code == 404
    assert resp.get_json() == {'error': 'Not found'}
    assert 'Traceback' not in caplog.text


def test_400_returns_json_without_traceback(client, caplog):
    # /storage/frames/post требует и files, и form — пустой POST -> abort(400)
    resp = client.post('/storage/frames/post')
    assert resp.status_code == 400
    assert resp.get_json() == {'error': 'Incorrect format'}
    assert 'Traceback' not in caplog.text
