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
        return "Processing, please wait...", 302
    elif status_result == "restarting":
        return "Server is restarting, please wait...", 305
    else:
        return "Error stopping server", 500

@app.route('/start', methods=['POST'])
def start():
    status_result = get_server_status()
    if status_result == "fully_loaded":
        return "Server is already running", 400
    # Start the server using a .bat inC:\VanillaServer\run.bat
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
    # Check if the request comes from an allowed IP
    if request.remote_addr not in ALLOWED_IPS:
        return "Unauthorized IP address", 403

    # Retrieve the Authorization header from the client request
    provided_auth_key = request.headers.get('Authorization')

    # Retrieve the expected auth key from the environment
    expected_auth_key = os.environ.get('SHUTDOWN_AUTH_KEY')

    # Validate the Authorization token
    if not provided_auth_key or provided_auth_key != f"Bearer {expected_auth_key}":
        return "Unauthorized", 403

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
        # Check if there's a window with the title 'MinecraftServer'
        windows = gw.getWindowsWithTitle('MinecraftServer')
        if windows:
            server = JavaServer(SERVER_IP, QUERY_PORT)
            try:
                query = server.query()
                if query:
                    return "fully_loaded"  # Server is fully loaded and connectable
            except Exception:
                return "booting"  # Server is booting but not connectable yet
        return "off"  # Server is off
    except Exception as e:
        print(f"Error checking server status: {e}")
        return "error"

def get_player_info():
    """Get the number of players currently online using the query port."""
    try:
        server = JavaServer(SERVER_IP, QUERY_PORT)
        query = server.query()
        return query.players.online
    except ConnectionError as e:
        print("Error getting player info:", e)
        return None

def perform_restart():
    """Perform the restart process in the background."""
    try:
        stop()
        time.sleep(20)  # Wait for the server to stop
        start()
    finally:
        global is_restarting
        is_restarting = False



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=37000)  # Change port if needed

