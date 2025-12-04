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

handler = logging.FileHandler(log_file, encoding='utf-8')
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logger = logging.getLogger('control_panel')
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())  # Also log to console
