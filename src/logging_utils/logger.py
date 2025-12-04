import logging
from pathlib import Path
from datetime import datetime
import sys
import colorama

colorama.init()

class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: colorama.Fore.CYAN,
        logging.INFO: colorama.Fore.GREEN,
        logging.WARNING: colorama.Fore.YELLOW,
        logging.ERROR: colorama.Fore.RED,
        logging.CRITICAL: colorama.Fore.MAGENTA,
    }
    RESET = colorama.Style.RESET_ALL

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"

if getattr(sys, 'frozen', False):
    log_dir = Path(sys.executable).parent / "logs"
else:
    log_dir = Path(__file__).resolve().parents[2] / "logs"
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"control_panel_{datetime.now().strftime('%Y%m%d')}.log"

file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(ColorFormatter(
    '[%(asctime)s] %(levelname)-8s | %(message)s',
    '%H:%M:%S',
))

logger = logging.getLogger('control_panel')
logger.setLevel(logging.INFO)
logger.propagate = False
logger.addHandler(file_handler)
logger.addHandler(console_handler)
