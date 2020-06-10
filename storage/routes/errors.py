from flask import current_app as app
from flask import make_response, jsonify


def setup_error_handlers():
    # for returning error as json file
    @app.errorhandler(404)
    def not_found(exception):
        app.logger.exception(exception)
        return make_response(jsonify({'error': 'Not found'}), 404)

    @app.errorhandler(400)
    def incorrect_format_400(exception):
        app.logger.exception(exception)
        return make_response(jsonify({'error': 'Incorrect format'}), 400)

    @app.errorhandler(500)
    def incorrect_format_500(exception):
        app.logger.exception(exception)
        return make_response(jsonify({'error': 'Internal Server'}), 500)
