import logging
import os
import time

date = time.strftime("%Y-%m-%d")
log_dir = '../ServerLogs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
log_file = os.path.join(log_dir, f'{date}_ServerSideLogs.txt')

logger = logging.getLogger('ServerLogger')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

if logger.hasHandlers():
    logger.handlers.clear()

logger.addHandler(file_handler)
logger.setLevel(logging.INFO)
