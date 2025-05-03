import configparser
import logging
import signal

from flask import Flask, request, jsonify
import time
from mcstatus import JavaServer
from mcrcon import MCRcon
import os
import subprocess
import pygetwindow as gw
import threading

app = Flask(__name__)

date = time.strftime("%Y-%m-%d")

# Set up logging
log_dir = 'ServerLogs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
log_file = os.path.join(log_dir, f'{date}_ServerSideLogs.txt')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Remove the default stream handler
if app.logger.hasHandlers():
    app.logger.handlers.clear()

app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

SERVER_IP = "localhost"
QUERY_PORT = 27002
RCON_PORT = 27001
# get password from config environment variable
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
last_player_count = 0
is_restarting = False
ALLOWED_IPS = ['127.0.0.1']  # Add your trusted IP addresses here

@app.before_request
def validate_auth_header():
    # Retrieve the Authorization header from the client request
    provided_auth_key = request.headers.get('Authorization')

    # Retrieve the expected auth key from the environment
    expected_auth_key = os.environ.get('AUTHKEY_SERVER_WEBSITE')

    # Validate the Authorization token
    if not provided_auth_key or provided_auth_key != f"Bearer {expected_auth_key}":
        return "Unauthorized", 403

@app.after_request
def after_request_logger(response):
    log_details = {
        "method": request.method,
        "url": request.url,
        "status": response.status_code,
        "remote_addr": request.remote_addr,
        "user_agent": request.user_agent.string
    }
    app.logger.info(f"Request: {log_details}")
    return response

@app.route('/status', methods=['GET'])
def status():
    status_result = get_server_status()
    if status_result == "fully_loaded":
        return "Server Machine is live!\nMinecraft Server is ONLINE", 200
    if status_result == "booting":
        return "Server Machine is live!\nMinecraft Server is BOOTING", 205
    if status_result == "off":
        return "Server Machine is live!\nMinecraft Server is OFFLINE", 206
    if status_result == "restarting":
        return "Server Machine is live!\nMinecraft Server is RESTARTING", 207
    return "Server Machine is OFFLINE", 500

@app.route('/stop', methods=['POST'])
def stop():
    status_result = get_server_status()
    if status_result == "off":
        return "Server is already offline", 400
    if status_result == "fully_loaded":
        send_rcon_command("stop")
        return "Server is stopping...", 200
    if status_result == "booting":
        return "Processing, please wait...", 302
    if status_result == "restarting":
        return "Server is restarting, please wait...", 305
    return "Error stopping server", 500

@app.route('/start', methods=['POST'])
def start():
    status_result = get_server_status()
    if status_result in ["fully_loaded", "booting", "restarting"]:
        return f"Server is already {status_result.replace('_', ' ')}", 400
    if status_result == "off":
        try:
            config_handler = ConfigFileHandler()
            server_location = config_handler.get_value('Run.bat location')
            os.chdir(server_location)
            subprocess.Popen("run.bat", creationflags=subprocess.CREATE_NEW_CONSOLE)
            return "Server is starting...", 200
        except ValueError as e:
            return str(e), 400
        except Exception as e:
            print(f"Error starting server: {e}")
            return "Error starting server", 500
    return "Error starting server", 500

@app.route('/restart', methods=['POST'])
def restart():
    global is_restarting
    if is_restarting:
        return "Server is already restarting", 400

    status_result = get_server_status()
    if status_result in ["off", "booting"]:
        return f"Server is already {status_result}", 400 if status_result == "off" else 302
    if status_result == "fully_loaded":
        is_restarting = True
        threading.Thread(target=perform_restart).start()
        return "Server is restarting...", 200
    return "Error restarting server", 500

@app.route('/players', methods=['GET'])
def players():
    global last_player_count
    player_count = get_player_info()
    if player_count is not None:
        last_player_count = player_count
        return f"Players online: {player_count}", 200
    else:
        return "Server is offline", 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    # Check if the request comes from an allowed IP
    if request.remote_addr not in ALLOWED_IPS:
        return "Unauthorized IP address", 403

    # Retrieve the shutdown header from the client request
    provided_auth_key = request.headers.get('shutdown-header')

    # Retrieve the expected auth key from the environment
    expected_auth_key = os.environ.get('SHUTDOWN_AUTH_KEY')

    # Validate the shutdown header
    if not provided_auth_key or provided_auth_key != expected_auth_key:
        return "Unauthorized, incorrect shutdown-down header", 403

    # Send the response to the client before shutting down
    def delayed_shutdown():
        time.sleep(2)  # Allow time for the client to finish processing
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=delayed_shutdown).start()
    return "Shutting down the server...", 200

def send_rcon_command(command):
    """Send a command to the Minecraft server via RCON."""
    try:
        with MCRcon(SERVER_IP, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command(command)
    except Exception as e:
        print(f"Error sending RCON command: {e}")

def get_server_status():
    global is_restarting
    if is_restarting:
        return "restarting"
    try:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            try:
                query = JavaServer(SERVER_IP, QUERY_PORT).query()
                return "fully_loaded" if query else "booting"
            except Exception:
                return "booting"
        return "off"
    except Exception as e:
        print(f"Error checking server status: {e}")
        return "error"

def get_player_info():
    """Get the number of players currently online using the query port."""
    try:
        query = JavaServer(SERVER_IP, QUERY_PORT).query()
        return query.players.online
    except ConnectionError as e:
        print(f"Error getting player info: {e}")
        return None

def perform_restart():
    """Perform the restart process in the background."""
    global is_restarting
    try:
        stop()
        time.sleep(20)  # Wait for the server to stop
        start()
    finally:
        is_restarting = False

class ConfigFileHandler:
    # Create a configuration file called config.ini
    def __init__(self):
        self.config_file = 'ServerConfig.ini'
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

if __name__ == '__main__':
    ConfigFileHandler().create_config_file()
    app.run(host='0.0.0.0', port=37000, debug=False)  # Change port if needed

