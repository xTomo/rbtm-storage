import logger

from flask import Flask
app = Flask(__name__)
app.config.from_envvar('YOURAPPLICATION_SETTINGS')


with app.app_context():

    logger.logger_setup()

    import \
        routes.storage, \
        routes.experiments, \
        routes.errors

    app.register_blueprint(routes.storage.bp_storage)
    app.register_blueprint(routes.experiments.bp_experiments)
    routes.errors.setup_error_handlers()
