import os
import sys
import logging
import threading
from logging.handlers import TimedRotatingFileHandler

LEVEL = logging.DEBUG

os.makedirs('logs', exist_ok=True)

log_format = '%(asctime)s - %(levelname)-8s - [%(funcName)-15s] - %(message)s'
date_format = '%H:%M:%S'

logger = logging.getLogger(__name__)
logger.setLevel(LEVEL)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

file_handler = TimedRotatingFileHandler(
    filename='logs/tagWorker.log',
    when='midnight',
    interval=1,
    backupCount=5,
    encoding='utf-8',
    utc=False
)
file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Captura excepciones no atrapadas (main thread)
def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Permite que Ctrl+C se maneje normalmente
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Excepción no capturada", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_uncaught_exception

# Captura excepciones no atrapadas en threads (Python 3.8+)
def handle_thread_exception(args):
    logger.critical("Excepción no capturada en hilo", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

threading.excepthook = handle_thread_exception
