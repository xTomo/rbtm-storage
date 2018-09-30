from flask import current_app as app


def logger_setup(logger_name):

    import os, logging
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

    logger = logging.getLogger('werkzeug')
    logger.setLevel(log_level)

    file_handler = configured_log_handler(RotatingFileHandler(logs_path, maxBytes=512000, backupCount=1))
    logger.addHandler(file_handler)

    if is_debug:
        stream_handler = configured_log_handler(StreamHandler())
        logger.addHandler(stream_handler)
