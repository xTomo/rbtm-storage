from flask import current_app


def logger_setup(logger_name):

    import os, logging
    from logging import StreamHandler
    from logging.handlers import RotatingFileHandler

    is_debug = current_app.config['DEBUG']

    log_level = logging.DEBUG if is_debug else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(name)s - [LINE:%(lineno)d]# - %(levelname)s - %(message)s")

    def configured_log_handler(log_handler):
        log_handler.setLevel(log_level)
        log_handler.setFormatter(formatter)
        return log_handler

    logs_path = os.path.join('logs', 'storage.log')
    if not os.path.exists(os.path.dirname(logs_path)):
        os.makedirs(os.path.dirname(logs_path))

    log = logging.getLogger(logger_name)
    log.setLevel(log_level)

    file_handler = configured_log_handler(RotatingFileHandler(logs_path, maxBytes=512000, backupCount=1))
    log.addHandler(file_handler)

    if is_debug:
        stream_handler = configured_log_handler(StreamHandler())
        log.addHandler(stream_handler)
