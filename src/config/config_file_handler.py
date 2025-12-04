import configparser
import sys
from pathlib import Path

# Use executable directory when frozen, otherwise use project root
if getattr(sys, 'frozen', False):
    # Running as executable - use the directory where the exe is located
    PROJECT_ROOT = Path(sys.executable).parent
else:
    # Running as script - use project root
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = PROJECT_ROOT / "ServerConfig.ini"


class ConfigFileHandler:
    def __init__(self):
        self.config_file = CONFIG_PATH
        self.config = configparser.ConfigParser()
        self.config.optionxform = str

    def create_config_file(self):
        if not self.config_file.exists():
            with open(self.config_file, 'w', encoding='utf-8') as configfile:
                self.config['PROPERTIES'] = {
                    'PlayitGG location': '',
                }
                configfile.write("# Configuration file for ServerSide Control Panel\n")
                configfile.write("# PlayitGG location: Path to playit.exe for tunneling\n")
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
