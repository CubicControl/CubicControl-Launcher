"""Websocket-enabled variant of the server-side API.

This file mirrors the original server API while emitting status updates over
Socket.IO so consumers can subscribe instead of polling ``/status``.
"""

import os
import signal
import subprocess
import threading
import time

import pygetwindow as gw
from flask import Flask, request
from flask_socketio import SocketIO
from mcrcon import MCRcon
from mcstatus import JavaServer

from lib import config, server_properties
from lib.Logger import logger
from lib.configFileHandler import ConfigFileHandler
from lib.setup_gui import InitialSetupGUI

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

is_restarting = False
is_stopping = False

_status_lock = threading.Lock()


@app.before_request
def validate_auth_header():
    provided_auth_key = request.headers.get('Authorization')
    expected_auth_key = config.AUTH_KEY
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
    logger.info(f"Request: {log_details}")
    return response


def _emit_status_update():
    status_payload = _build_status_payload()
    socketio.emit("status_update", status_payload)


def _build_status_payload():
    status_text, status_code = _status_message()
    return {"status": status_text, "status_code": status_code}


def _status_message():
    status_result = get_server_status()
    if status_result == "fully_loaded":
        return "Server Machine is live!\nMinecraft Server is ONLINE", 200
    if status_result == "starting":
        return "Server Machine is live!\nMinecraft Server is STARTING", 205
    if status_result == "off":
        return "Server Machine is live!\nMinecraft Server is OFFLINE", 206
    if status_result == "restarting":
        return "Server Machine is live!\nMinecraft Server is RESTARTING", 207
    if status_result == "stopping":
        return "Server Machine is live!\nMinecraft Server is STOPPING", 208
    return "Server Machine is OFFLINE", 500



@socketio.on('connect')
def on_connect():
    _emit_status_update()


@socketio.on('request_status')
def on_request_status():
    _emit_status_update()


@app.route('/status', methods=['GET'])
def status():
    message, status_code = _status_message()
    return message, status_code


@app.route('/stop', methods=['POST'])
def stop():
    global is_stopping
    status_result = get_server_status()
    if status_result == "off":
        return "Server is already offline", 400
    if status_result == "fully_loaded":
        is_stopping = True
        send_rcon_command("stop")
        _emit_status_update()
        return "Server is stopping...", 200
    if status_result == "starting":
        return "Processing, please wait...", 302
    if status_result == "restarting":
        return "Server is restarting, please wait...", 305
    return "Error stopping server", 500


@app.route('/start', methods=['POST'])
def start():
    status_result = get_server_status()
    if status_result in ["fully_loaded", "starting", "restarting"]:
        return f"Server is already {status_result.replace('_', ' ')}", 400
    if status_result == "off":
        try:
            config_handler = ConfigFileHandler()
            server_location = config_handler.get_value('Run.bat location')
            os.chdir(server_location)
            subprocess.Popen("run.bat", creationflags=subprocess.CREATE_NEW_CONSOLE)
            _emit_status_update()
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
    if status_result in ["off", "starting"]:
        return f"Server is already {status_result}", 400 if status_result == "off" else 302
    if status_result == "fully_loaded":
        is_restarting = True
        threading.Thread(target=perform_restart).start()
        _emit_status_update()
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
def shutdown_api():
    if request.remote_addr not in config.ALLOWED_IPS:
        return "Unauthorized IP address", 403

    provided_auth_key = request.headers.get('shutdown-header')
    expected_auth_key = os.environ.get('SHUTDOWN_AUTH_KEY')

    if not provided_auth_key or provided_auth_key != expected_auth_key:
        return "Unauthorized, incorrect shutdown-down header", 403

    def delayed_shutdown():
        time.sleep(2)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=delayed_shutdown).start()
    return "Shutting down the server...", 200


def send_rcon_command(command):
    try:
        with MCRcon(config.SERVER_IP, config.RCON_PASSWORD, port=config.RCON_PORT) as mcr:
            mcr.command(command)
    except Exception as e:  # pragma: no cover - defensive logging only
        logger.error(f"Error sending RCON command: {e}. Please ensure RCON queries are enabled and the password and port are correct.")
        print(f"Error sending RCON command: {e}. Please ensure RCON queries are enabled and the password and port are correct.")
        return f"Error sending RCON command: {e}"


def get_server_status():
    global is_restarting, is_stopping
    if is_restarting:
        return "restarting"
    if is_stopping:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if not windows:
            is_stopping = False
            return "off"
        return "stopping"
    try:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            try:
                query = JavaServer(config.SERVER_IP, config.QUERY_PORT).query()
                return "fully_loaded" if query else "starting"
            except Exception:
                return "starting"
        return "off"
    except Exception as e:  # pragma: no cover - defensive logging only
        print(f"Error checking server status: {e}")
        return "error"


def get_player_info():
    try:
        query = JavaServer(config.SERVER_IP, config.QUERY_PORT).query()
        return query.players.online
    except ConnectionError as e:  # pragma: no cover - defensive logging only
        print(f"Error getting player info: {e}")
        return None

def perform_restart():
    """Perform the restart process in the background."""
    global is_restarting
    try:
        is_restarting = True

        # 1) Stop the server directly via RCON
        send_rcon_command("stop")
        _emit_status_update()  # optional: let clients know it's stopping

        # 2) Wait for it to fully stop (you could improve this by polling status instead of fixed sleep)
        time.sleep(20)

        # 3) Start the server directly (same logic as /start)
        try:
            config_handler = ConfigFileHandler()
            server_location = config_handler.get_value('Run.bat location')
            os.chdir(server_location)
            subprocess.Popen("run.bat", creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as e:
            logger.error(f"Error starting server during restart: {e}")
        finally:
            _emit_status_update()

    finally:
        is_restarting = False

def needs_initial_setup() -> bool:
    """Return True if we should show the Tkinter setup window before starting the server."""
    # Check basic env vars
    required_env = ['RCON_PASSWORD', 'AUTHKEY_SERVER_WEBSITE']
    for name in required_env:
        if not os.environ.get(name):
            return True

    cfg = ConfigFileHandler()
    try:
        server_folder = cfg.get_value('Run.bat location')
    except Exception:
        return True

    if not server_folder or not os.path.isdir(server_folder):
        return True

    props_path = os.path.join(server_folder, 'server.properties')
    if not os.path.exists(props_path):
        return True

    props = server_properties.parse_server_properties(props_path)
    required_props = ['enable-rcon', 'rcon.password', 'rcon.port', 'enable-query', 'query.port']
    for key in required_props:
        if key not in props or not props[key]:
            return True

    return False



if __name__ == '__main__':
    ConfigFileHandler().create_config_file()

    # Run the setup GUI only if something important is missing
    if needs_initial_setup():
        InitialSetupGUI()

    socketio.run(app, host='0.0.0.0', port=37000, debug=False)