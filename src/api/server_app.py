"""Websocket-enabled variant of the server-side API."""

import os
import signal
import threading
import time

import pygetwindow as gw
import requests
from flask import Flask, request
from flask_socketio import SocketIO
from mcrcon import MCRcon
from mcstatus import JavaServer

from src.config import settings
from src.config.config_file_handler import ConfigFileHandler
from src.logging_utils.logger import logger

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

is_restarting = False
is_stopping = False
is_stopping_since = None  # Timestamp when stopping started
last_player_count = 0
shutdown_requested = False  # Flag to signal shutdown


@app.before_request
def validate_auth_header():
    provided_auth_key = request.headers.get('Authorization')
    expected_auth_key = settings.AUTH_KEY
    if not provided_auth_key or provided_auth_key != f"Bearer {expected_auth_key}":
        return "Unauthorized", 403


@app.after_request
def after_request_logger(response):
    log_details = {
        "method": request.method,
        "url": request.url,
        "status": response.status_code,
        "remote_addr": request.remote_addr,
        "user_agent": request.user_agent.string,
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
        return "Server Machine is live!\nMinecraft Server is RUNNING", 200
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


def _status_response():
    message, status_code = _status_message()
    return message, status_code


def _stop_server():
    """Stop the Minecraft server by calling the control panel API."""
    global is_stopping, is_stopping_since
    status_result = get_server_status()
    if status_result == "off":
        return "Server is already offline", 400
    if status_result == "fully_loaded":
        try:
            is_stopping = True
            is_stopping_since = time.time()
            # Call the control panel API to stop the server
            import requests
            headers = {"Authorization": f"Bearer {settings.ADMIN_AUTH_KEY}"}
            response = requests.post("http://localhost:38000/api/stop/server", headers=headers, timeout=5)
            _emit_status_update()
            if response.status_code == 200:
                return "Server is stopping...", 200
            else:
                is_stopping = False
                is_stopping_since = None
                error_msg = response.json().get("error", "Unknown error")
                return f"Error stopping server: {error_msg}", response.status_code
        except requests.RequestException as exc:
            is_stopping = False
            is_stopping_since = None
            logger.error(f"Error calling control panel API to stop server: {exc}")
            return "Error stopping server: Cannot reach control panel", 500
        except Exception as exc:
            is_stopping = False
            is_stopping_since = None
            logger.error(f"Error stopping server: {exc}")
            return "Error stopping server", 500
    if status_result == "starting":
        return "Processing, please wait...", 302
    if status_result == "restarting":
        return "Server is restarting, please wait...", 305
    return "Error stopping server", 500


def _start_server():
    """Start the Minecraft server by calling the control panel API."""
    status_result = get_server_status()
    if status_result in ["fully_loaded", "starting", "restarting"]:
        return f"Server is already {status_result.replace('_', ' ')}", 400
    if status_result == "off":
        try:
            # Call the control panel API to start the server
            import requests
            headers = {"Authorization": f"Bearer {settings.ADMIN_AUTH_KEY}"}
            response = requests.post("http://localhost:38000/api/start/server", headers=headers, timeout=5)
            if response.status_code == 200:
                _emit_status_update()
                return "Server is starting...", 200
            else:
                error_msg = response.json().get("error", "Unknown error")
                return f"Error starting server: {error_msg}", response.status_code
        except requests.RequestException as exc:
            logger.error(f"Error calling control panel API to start server: {exc}")
            return "Error starting server: Cannot reach control panel", 500
        except Exception as exc:
            logger.error(f"Error starting server: {exc}")
            return "Error starting server", 500
    return "Error starting server", 500


def _restart_server():
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


@app.route('/status', methods=['GET'])
def status():
    return _status_response()


@app.route('/api/server/status', methods=['GET'])
def status_v2():
    return _status_response()


@app.route('/stop', methods=['POST'])
def stop():
    return _stop_server()


@app.route('/api/server/stop', methods=['POST'])
def stop_v2():
    return _stop_server()


@app.route('/start', methods=['POST'])
def start():
    return _start_server()


@app.route('/api/server/start', methods=['POST'])
def start_v2():
    return _start_server()


@app.route('/restart', methods=['POST'])
def restart():
    return _restart_server()


@app.route('/api/server/restart', methods=['POST'])
def restart_v2():
    return _restart_server()


@app.route('/players', methods=['GET'])
def players():
    global last_player_count
    player_count = get_player_info()
    if player_count is not None:
        last_player_count = player_count
        return f"Players online: {player_count}", 200
    return "Server is offline", 500


@app.route('/shutdown', methods=['POST'])
def shutdown_api():
    global shutdown_requested

    if request.remote_addr not in settings.ALLOWED_IPS:
        return "Unauthorized IP address", 403

    provided_auth_key = request.headers.get('shutdown-header')
    expected_auth_key = os.environ.get('SHUTDOWN_AUTH_KEY')

    if not provided_auth_key or provided_auth_key != expected_auth_key:
        return "Unauthorized, incorrect shutdown-down header", 403

    # Check if running as subprocess or thread
    import sys
    if getattr(sys, 'frozen', False):
        # Running in thread mode (frozen exe) - use proper shutdown
        logger.info("API shutdown requested (thread mode)")

        def delayed_shutdown():
            time.sleep(0.5)  # Brief delay to allow response to send
            try:
                # Stop the SocketIO server gracefully
                socketio.stop()
                logger.info("SocketIO server stopped")
            except Exception as e:
                logger.error(f"Error stopping SocketIO: {e}")
                # Force exit as last resort
                os._exit(0)

        threading.Thread(target=delayed_shutdown, daemon=True).start()
        return "API shutting down...", 200
    else:
        # Running as subprocess - can kill process
        def delayed_shutdown():
            time.sleep(1)
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=delayed_shutdown, daemon=True).start()
        return "Shutting down the API server...", 200


def send_rcon_command(command):
    try:
        with MCRcon(settings.SERVER_IP, settings.RCON_PASSWORD, port=settings.RCON_PORT) as mcr:
            mcr.command(command)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error(
            f"Error sending RCON command: {exc}. Please ensure RCON queries are enabled and the password and port are correct."
        )
        print(
            f"Error sending RCON command: {exc}. Please ensure RCON queries are enabled and the password and port are correct."
        )
        return f"Error sending RCON command: {exc}"


def get_server_status():
    global is_restarting, is_stopping, is_stopping_since

    if is_restarting:
        return "restarting"

    if is_stopping:
        # Check if stopping timeout has been exceeded (30 seconds)
        if is_stopping_since and (time.time() - is_stopping_since) > 30:
            logger.warning("is_stopping timeout exceeded, resetting flag")
            is_stopping = False
            is_stopping_since = None
            # Continue to normal status check
        else:
            # Check if server is actually stopped
            server_is_off = _check_server_actually_off()
            if server_is_off:
                is_stopping = False
                is_stopping_since = None
                return "off"
            # Still stopping
            return "stopping"

    # Normal status check when not stopping
    try:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            try:
                query = JavaServer(settings.SERVER_IP, settings.QUERY_PORT).query()
                return "fully_loaded" if query else "starting"
            except Exception:
                return "starting"
        return "off"
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"Error checking server status: {exc}")
        return "error"


def _check_server_actually_off():
    """Check if the server is actually off by checking both window and query."""
    # Try to query the server
    try:
        JavaServer(settings.SERVER_IP, settings.QUERY_PORT).query()
        return False  # Server is responding, not off
    except Exception:
        pass  # Query failed, continue checking

    # Try to check if window exists
    try:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            return False  # Window exists, not off
    except Exception:
        pass  # Can't check windows, assume off if query also failed

    # Both query and window check indicate server is off
    return True


def get_player_info():
    try:
        query = JavaServer(settings.SERVER_IP, settings.QUERY_PORT).query()
        return query.players.online
    except ConnectionError as exc:  # pragma: no cover - defensive logging only
        print(f"Error getting player info: {exc}")
        return None


def perform_restart():
    """Perform the restart process in the background."""
    global is_restarting
    try:
        is_restarting = True

        # 1) Stop the server via control panel API
        try:
            headers = {"Authorization": f"Bearer {settings.ADMIN_AUTH_KEY}"}
            requests.post("http://localhost:38000/api/stop/server", headers=headers, timeout=5)
            _emit_status_update()
        except Exception as exc:
            logger.error(f"Error stopping server during restart: {exc}")

        # 2) Wait for it to fully stop
        time.sleep(20)

        # 3) Start the server via control panel API
        try:
            headers = {"Authorization": f"Bearer {settings.ADMIN_AUTH_KEY}"}
            requests.post("http://localhost:38000/api/start/server", headers=headers, timeout=5)
            _emit_status_update()
        except Exception as exc:
            logger.error(f"Error starting server during restart: {exc}")

    finally:
        is_restarting = False


if __name__ == '__main__':
    ConfigFileHandler().create_config_file()

    socketio.run(app, host='0.0.0.0', port=37000, debug=False)
