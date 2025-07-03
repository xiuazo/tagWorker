import os
import logging
from logging.handlers import TimedRotatingFileHandler

LEVEL=logging.DEBUG

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
    backupCount=15,
    encoding='utf-8',
    utc=False
)
file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

logger.addHandler(console_handler)
logger.addHandler(file_handler)
