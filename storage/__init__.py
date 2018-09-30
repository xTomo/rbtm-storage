import os
import logging


from flask import Flask, make_response, jsonify
app = Flask(__name__)
app.config.from_envvar('YOURAPPLICATION_SETTINGS')


def logger_setup():

    from logging import StreamHandler
    from logging.handlers import RotatingFileHandler

    is_debug = app.config['DEBUG']

    log_level = logging.DEBUG if is_debug else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(name)s - [LINE:%(lineno)d]# - %(levelname)s - %(message)s")

    def configured_log_handler(log_handler):
        log_handler.setLevel(log_level)
        log_handler.setFormatter(formatter)
        return log_handler

    logs_path = os.path.join('logs', 'storage.log')
    if not os.path.exists(os.path.dirname(logs_path)):
        os.makedirs(os.path.dirname(logs_path))

    log = logging.getLogger('werkzeug')
    log.setLevel(log_level)

    file_handler = configured_log_handler(RotatingFileHandler(logs_path, maxBytes=512000, backupCount=1))
    app.logger.addHandler(file_handler)
    log.addHandler(file_handler)

    if is_debug:
        stream_handler = configured_log_handler(StreamHandler())
        app.logger.addHandler(stream_handler)
        log.addHandler(stream_handler)


logger_setup()

import storage.views

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
