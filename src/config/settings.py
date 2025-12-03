import os

SERVER_IP = "localhost"
QUERY_PORT = 27002
RCON_PORT = 27001
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
last_player_count = 0
is_restarting = False
ALLOWED_IPS = ['127.0.0.1']  # Add your trusted IP addresses here
AUTH_KEY = os.environ.get('AUTHKEY_SERVER_WEBSITE') or "TEST"
ADMIN_AUTH_KEY = os.environ.get('ADMIN_AUTH_KEY') or "ADMIN_TEST"
