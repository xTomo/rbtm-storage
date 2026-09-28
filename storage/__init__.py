import os

from . import logger

from flask import Flask
app = Flask(__name__)

# silent=True: storage/conf.py в .gitignore, а генерация его в Dockerfile
# закомментирована (RUN echo ... > conf.py) — без silent=True отсутствие
# файла роняло бы импорт пакета целиком. Если conf.py присутствует, он
# по-прежнему имеет приоритет (перезаписывает значения ниже).
app.config.from_envvar('YOURAPPLICATION_SETTINGS', silent=True)
app.config.setdefault('MONGODB_URI', os.environ.get('MONGODB_URI', 'mongodb://database:27017'))
app.config.setdefault('DEBUG', False)


with app.app_context():
    logger.logger_setup()

    from .routes import storage, experiments, errors

    app.register_blueprint(storage.bp_storage)
    app.register_blueprint(experiments.bp_experiments)
    errors.setup_error_handlers()
