import configparser
import sys
from pathlib import Path
from typing import Optional

class ConfigFileHandler:
    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            if getattr(sys, 'frozen', False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).resolve().parents[2]
            data_dir = base / "data"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "PlayitConfig.ini"
        self.config = configparser.ConfigParser()
        self.config.optionxform = str

    def create_config_file(self):
        if not self.config_file.exists():
            with open(self.config_file, 'w', encoding='utf-8') as configfile:
                self.config['PROPERTIES'] = {
                    'Playit location': '',
                }
                configfile.write("# Configuration file for ServerSide Control Panel\n")
                configfile.write("# Playit location: Path to playit.exe for tunneling\n")
                self.config.write(configfile)

    def get_value(self, value: str, *, allow_empty: bool = False):
        if not self.config_file.exists():
            self.create_config_file()
        self.config.read(self.config_file)
        prop_value = self.config.get('PROPERTIES', value, fallback='')
        if prop_value == '' and not allow_empty:
            raise ValueError("Incorrect run.bat location. Please update the ServerConfig.ini file.")
        return prop_value

    def set_value(self, key: str, value: str):
        """Set a value in the PROPERTIES section and save to disk."""
        if not self.config_file.exists():
            self.create_config_file()
        self.config.read(self.config_file)
        if 'PROPERTIES' not in self.config:
            self.config['PROPERTIES'] = {}
        self.config['PROPERTIES'][key] = value
        with open(self.config_file, 'w', encoding='utf-8') as configfile:
            self.config.write(configfile)
