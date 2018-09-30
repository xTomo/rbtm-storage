import logger

from flask import Flask, make_response, jsonify
app = Flask(__name__)
app.config.from_envvar('YOURAPPLICATION_SETTINGS')


with app.app_context():
    logger.logger_setup()

    import views, routes.errors as re

    app.register_blueprint(views.bp_experiments)
    app.register_blueprint(views.bp_storage)
    re.setup_error_handlers()

