import os
import logging

from flask import Flask
app = Flask(__name__)


def logger_setup():

    from logging import StreamHandler
    from logging.handlers import RotatingFileHandler

    log_level = logging.DEBUG
    formatter = logging.Formatter("%(asctime)s - %(name)s - [LINE:%(lineno)d]# - %(levelname)s - %(message)s")

    def configured_log_handler(log_handler):
        log_handler.setLevel(log_level)
        log_handler.setFormatter(formatter)
        return log_handler

    logs_path = os.path.join('logs', 'storage.log')
    if not os.path.exists(os.path.dirname(logs_path)):
        os.makedirs(os.path.dirname(logs_path))

    file_handler = configured_log_handler(RotatingFileHandler(logs_path, maxBytes=512000, backupCount=1))
    stream_handler = configured_log_handler(StreamHandler())

    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)

    log = logging.getLogger('werkzeug')
    log.setLevel(log_level)

    log.addHandler(file_handler)
    log.addHandler(stream_handler)


logger_setup()
