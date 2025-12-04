import logging
from pathlib import Path
from datetime import datetime
import sys

if getattr(sys, 'frozen', False):
    # If running as a PyInstaller executable, put logs next to the .exe
    log_dir = Path(sys.executable).parent / "logs"
else:
    # Otherwise, use project root
    log_dir = Path(__file__).resolve().parents[2] / "logs"
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"control_panel_{datetime.now().strftime('%Y%m%d')}.log"

file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

# Console handler with a concise, uniform format for readability
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)-8s | %(message)s',
    '%H:%M:%S',
))

logger = logging.getLogger('control_panel')
logger.setLevel(logging.INFO)
logger.propagate = False
logger.addHandler(file_handler)
logger.addHandler(console_handler)
