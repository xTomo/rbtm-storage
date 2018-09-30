import constants, logger

from flask import Flask, make_response, jsonify
app = Flask(__name__)
app.config.from_envvar('YOURAPPLICATION_SETTINGS')


with app.app_context():
    logger.logger_setup(constants.LOGGER_NAME)


from storage import views

app.register_blueprint(views.bp_experiments)
app.register_blueprint(views.bp_storage)


# for returning error as json file
@app.errorhandler(404)
def not_found(exception):
    app.logger.exception(exception)
    return make_response(jsonify({'error': 'Not found'}), 404)


@app.errorhandler(400)
def incorrect_format(exception):
    app.logger.exception(exception)
    return make_response(jsonify({'error': 'Incorrect format'}), 400)


@app.errorhandler(500)
def incorrect_format(exception):
    app.logger.exception(exception)
    return make_response(jsonify({'error': 'Internal Server'}), 500)
