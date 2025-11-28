import configparser
import os


class ConfigFileHandler:
    def __init__(self):
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ServerConfig.ini')
        self.config = configparser.ConfigParser()
        self.config.optionxform = str

    def create_config_file(self):
        if not os.path.exists(self.config_file):
            with open(self.config_file, 'w') as configfile:
                self.config['PROPERTIES'] = {'Run.bat location': ''}
                configfile.write("# Location of run.bat of the server you want to start\n")
                self.config.write(configfile)

    def get_value(self, value):
        if not os.path.exists(self.config_file):
            self.create_config_file()
        self.config.read(self.config_file)
        try:
            prop_value = self.config.get('PROPERTIES', value)
            if prop_value == '':
                raise ValueError("Incorrect run.bat location. Please update the ServerConfig.ini file.")
            return prop_value
        except Exception as e:
            print(f"Error retrieving value: {e}")
            raise

    def set_value(self, key: str, value: str):
        """Set a value in the PROPERTIES section and save to disk."""
        if not os.path.exists(self.config_file):
            self.create_config_file()
        self.config.read(self.config_file)
        if 'PROPERTIES' not in self.config:
            self.config['PROPERTIES'] = {}
        self.config['PROPERTIES'][key] = value
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)