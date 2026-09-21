"""
storage/__init__.py не должен падать, если storage/conf.py отсутствует
(он в .gitignore, генерация в Dockerfile закомментирована) — используются
дефолты (MONGODB_URI='mongodb://database:27017' если не задан env-переменной).
"""
import pathlib
import sys

import pytest


@pytest.fixture
def _clean_storage_modules():
    for mod_name in list(sys.modules):
        if mod_name == 'storage' or mod_name.startswith('storage.'):
            del sys.modules[mod_name]
    yield
    for mod_name in list(sys.modules):
        if mod_name == 'storage' or mod_name.startswith('storage.'):
            del sys.modules[mod_name]


def test_import_succeeds_without_conf_py(tmp_path, monkeypatch, _clean_storage_modules):
    monkeypatch.chdir(tmp_path)
    missing_conf = str(tmp_path / 'no-such-conf.py')
    monkeypatch.setenv('YOURAPPLICATION_SETTINGS', missing_conf)
    monkeypatch.delenv('MONGODB_URI', raising=False)

    import storage as storage_pkg  # не должно бросить исключение

    assert storage_pkg.app.config['MONGODB_URI'] == 'mongodb://database:27017'


def test_mongodb_uri_env_var_overrides_default(tmp_path, monkeypatch, _clean_storage_modules):
    monkeypatch.chdir(tmp_path)
    missing_conf = str(tmp_path / 'no-such-conf.py')
    monkeypatch.setenv('YOURAPPLICATION_SETTINGS', missing_conf)
    monkeypatch.setenv('MONGODB_URI', 'mongodb://custom-host:27017')

    import storage as storage_pkg

    assert storage_pkg.app.config['MONGODB_URI'] == 'mongodb://custom-host:27017'


def test_conf_py_style_file_still_takes_priority(tmp_path, monkeypatch, _clean_storage_modules):
    conf_path = tmp_path / 'conf_present.py'
    conf_path.write_text("MONGODB_URI = 'mongodb://from-conf-file:27017'\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('YOURAPPLICATION_SETTINGS', str(conf_path))

    import storage as storage_pkg

    assert storage_pkg.app.config['MONGODB_URI'] == 'mongodb://from-conf-file:27017'
