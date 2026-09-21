from flask import current_app as app
from flask import make_response, jsonify, request


def setup_error_handlers():
    # for returning error as json file
    @app.errorhandler(404)
    def not_found(exception):
        # 404 — обычный клиентский случай (опечатка в пути, отсутствующий ресурс),
        # трейсбек тут не нужен и только засоряет лог; путь достаточно для диагностики.
        app.logger.warning(f'404 Not found: {request.path}')
        return make_response(jsonify({'error': 'Not found'}), 404)

    @app.errorhandler(400)
    def incorrect_format_400(exception):
        app.logger.warning(f'400 Incorrect format: {request.path}')
        return make_response(jsonify({'error': 'Incorrect format'}), 400)

    @app.errorhandler(500)
    def incorrect_format_500(exception):
        # 500 — неожиданная ошибка сервера, трейсбек нужен для диагностики
        app.logger.exception(exception)
        return make_response(jsonify({'error': 'Internal Server'}), 500)
