import os

SERVER_IP = "localhost"
QUERY_PORT = 27002
RCON_PORT = 27001
RCON_PASSWORD = os.environ.get('RCON_PASSWORD')
last_player_count = 0
is_restarting = False
ALLOWED_IPS = ['127.0.0.1']  # Add your trusted IP addresses here
# Dedicated port for the lightweight public API. Kept fixed to avoid accidental
# collisions with the panel port (38000) and to simplify reverse-proxy setups.
PUBLIC_API_PORT = 38001

# AUTH keys are now persisted once in the data folder and reused everywhere.
try:
    from src.config.secret_store import SecretStore

    _secret_store = SecretStore()
    _admin_key, _auth_key = _secret_store.get_keys()
except Exception:
    _secret_store = None
    _admin_key, _auth_key = "", ""

AUTH_KEY = _auth_key
ADMIN_AUTH_KEY = _admin_key


def apply_auth_keys(admin_key: str, auth_key: str) -> None:
    """Update in-memory copies of the global auth keys."""
    global ADMIN_AUTH_KEY, AUTH_KEY
    ADMIN_AUTH_KEY = admin_key or ""
    AUTH_KEY = auth_key or ""
