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
from flask_socketio import SocketIO
import eventlet

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet' ,cors_allowed_origins="*")

SERVER_IP = "localhost"
QUERY_PORT = 27002
RCON_PORT = 27001
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
last_player_count = 0
is_restarting = False
ALLOWED_IPS = ['127.0.0.1']

# Configure logging to log to both file and console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H-%M-%S"
)

file_handler = logging.FileHandler("flask_logs.txt")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H-%M-%S"))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H-%M-%S"))

logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)



@app.before_request
def validate_auth_header():
    provided_auth_key = request.headers.get('Authorization')
    expected_auth_key = os.environ.get('AUTHKEY_SERVER_WEBSITE')
    if not provided_auth_key or provided_auth_key != f"Bearer {expected_auth_key}":
        return "Unauthorized", 403

@app.route('/status', methods=['GET'])
def status():
    status_result = get_server_status()
    if status_result == "fully_loaded":
        return ("Server Machine is live!\n"
                "Minecraft Server is ONLINE"), 200
    elif status_result == "booting":
        return "Server Machine is live!\nMinecraft Server is BOOTING", 205
    elif status_result == "off":
        return "Server Machine is live!\nMinecraft Server is OFFLINE", 206
    elif status_result == "restarting":
        return "Server Machine is live!\nMinecraft Server is RESTARTING", 207
    else:
        return "Server Machine is OFFLINE", 500

@app.route('/stop', methods=['POST'])
def stop():
    status_result = get_server_status()
    if status_result == "off":
        return "Server is already offline", 400
    elif status_result == "fully_loaded":
        send_rcon_command("stop")
        return "Server is stopping...", 200
    elif status_result == "booting":
        return "Server is still booting, please wait...", 302
    elif status_result == "restarting":
        return "Server is restarting, please wait...", 305
    else:
        return "Error stopping server", 500

@app.route('/start', methods=['POST'])
def start():
    status_result = get_server_status()
    if status_result == "fully_loaded":
        return "Server is already running", 400
    elif status_result == "booting":
        return "Server is still booting, please wait...", 400
    elif status_result == "restarting":
        return "Server is restarting, please wait...", 400
    elif status_result == "off":
        os.chdir("C:\\VanillaServer")
        subprocess.Popen("run.bat", creationflags=subprocess.CREATE_NEW_CONSOLE)
        return "Server is starting...", 200
    else:
        return "Error starting server", 500

@app.route('/restart', methods=['POST'])
def restart():
    global is_restarting
    if is_restarting:
        return "Server is already restarting", 400

    status_result = get_server_status()
    if status_result == "off":
        return "Server is already offline", 400
    elif status_result == "booting":
        return "Server is still booting, please wait...", 302
    elif status_result == "fully_loaded":
        is_restarting = True
        threading.Thread(target=perform_restart).start()
        return "Server is restarting...", 200
    else:
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
    if not request.remote_addr or request.remote_addr not in ALLOWED_IPS:
        return "Unauthorized IP address", 403

    provided_auth_key = request.headers.get('Authorization')
    expected_auth_key = os.environ.get('SHUTDOWN_AUTH_KEY')
    if not provided_auth_key or provided_auth_key != f"Bearer {expected_auth_key}":
        return "Unauthorized", 403

    def delayed_shutdown():
        time.sleep(2)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=delayed_shutdown).start()
    return "Shutting down the server...", 200

def send_rcon_command(command):
    try:
        with MCRcon(SERVER_IP, RCON_PASSWORD, port=RCON_PORT) as mcr:
            mcr.command(command)
    except Exception as e:
        logging.error(f"Error sending RCON command: {e}")

def get_server_status():
    global is_restarting
    if is_restarting:
        return "restarting"
    try:
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            server = JavaServer(SERVER_IP, QUERY_PORT)
            try:
                query = server.query()
                if query:
                    return "fully_loaded"
            except Exception:
                return "booting"
        return "off"
    except Exception as e:
        logging.error(f"Error checking server status: {e}")
        return "error"

def get_player_info():
    try:
        server = JavaServer(SERVER_IP, QUERY_PORT)
        query = server.query()
        return query.players.online
    except ConnectionError as e:
        logging.error("Error getting player info:", e)
        return None

def perform_restart():
    try:
        stop()
        time.sleep(15)
        start()
    finally:
        global is_restarting
        is_restarting = False

def broadcast_status_update():
    status_result = get_server_status()
    status_map = {
        "fully_loaded": {"host_status": "online", "minecraft_status": "online"},
        "booting": {"host_status": "online", "minecraft_status": "loading"},
        "off": {"host_status": "online", "minecraft_status": "offline"},
        "restarting": {"host_status": "online", "minecraft_status": "loading"},
        "error": {"host_status": "offline", "minecraft_status": "offline"},
    }
    data = status_map.get(status_result, {"host_status": "offline", "minecraft_status": "offline"})
    socketio.emit('status_update', data)

def monitor_server_status():
    while True:
        broadcast_status_update()
        eventlet.sleep(4)

# Start the background task with eventlet.spawn
eventlet.spawn(monitor_server_status)

if __name__ == '__main__':
    print("Starting server...")
    socketio.run(app, host='0.0.0.0', port=37000)
