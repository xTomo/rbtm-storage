from . import logger

from flask import Flask
app = Flask(__name__)
app.config.from_envvar('YOURAPPLICATION_SETTINGS')


with app.app_context():
    logger.logger_setup()

    from .routes import storage, experiments, errors

    app.register_blueprint(storage.bp_storage)
    app.register_blueprint(experiments.bp_experiments)
    errors.setup_error_handlers()
