import os
import sys
from src.interface.control_panel import main as run_control_panel


def extract_guide_html():
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        base_path = sys._MEIPASS
    else:
        # Running in normal Python environment
        base_path = os.path.dirname(os.path.abspath(__file__))

    source_path = os.path.join(base_path, 'docs', 'guide.html')
    target_dir = os.path.join(os.getcwd(), 'docs')
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, 'guide.html')

    if os.path.exists(source_path) and not os.path.exists(target_path):
        import shutil
        shutil.copy2(source_path, target_path)

if __name__ == "__main__":
    extract_guide_html()
    run_control_panel()