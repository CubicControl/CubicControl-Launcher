import atexit
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import webbrowser
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional

import flask.cli
import psutil
import requests
from flask import Flask, jsonify, render_template, request, redirect, session, url_for
from flask_socketio import SocketIO, emit, join_room
from mcrcon import MCRcon
from mcstatus import JavaServer

from src.config import settings
from src.config.auth_handler import AuthHandler
from src.config.caddy_handler import CaddyManager
from src.config.config_file_handler import ConfigFileHandler
from src.config.secret_store import SecretStore
from src.controller.server_controller import ServerController
from src.interface.server_profiles import ServerProfile, ServerProfileStore
from src.logging_utils.logger import logger

APP_DIR = Path(__file__).resolve().parent

warnings.filterwarnings(
    "ignore",
    message=r"Werkzeug appears to be used in a production deployment",
)

flask.cli.show_server_banner = lambda *args, **kwargs: None  # hide Flask banner

for noisy in ("werkzeug", "engineio", "socketio", "flask_socketio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

_single_instance_lock = None
_instance_socket = None


def _acquire_single_instance_lock() -> Path:
    """
    Prevent multiple instances by locking a temp file.
    Works for both frozen executables and normal Python runs.
    """
    global _single_instance_lock, _instance_socket

    lock_path = Path(tempfile.gettempdir()) / "minrefact_control_panel.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # If a previous lock exists, check whether the recorded PID is still alive.
    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip() or "0")
            if existing_pid and psutil.pid_exists(existing_pid):
                raise RuntimeError("Another control panel instance is already running.")
        except ValueError:
            # Corrupted PID; fall through to lock attempt
            pass
        except RuntimeError:
            raise
        # Stale lock; remove before acquiring
        try:
            lock_path.unlink()
        except Exception:
            pass

    handle = open(lock_path, "a+")

    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another control panel instance is already running.") from exc
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Use a small localhost port as a second guard. Exclusive bind blocks duplicates
        # even if the file lock is stale or ignored.
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            _instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            # SO_EXCLUSIVEADDRUSE prevents socket reuse on Windows
            _instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        _instance_socket.bind(("127.0.0.1", 38999))
        _instance_socket.listen(1)

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _single_instance_lock = handle
        return lock_path
    except Exception:
        try:
            handle.close()
        except Exception:
            pass
        if _instance_socket:
            try:
                _instance_socket.close()
            except Exception:
                pass
            _instance_socket = None
        raise


def _release_single_instance_lock() -> None:
    global _single_instance_lock, _instance_socket
    lock_path = Path(tempfile.gettempdir()) / "minrefact_control_panel.lock"

    if not _single_instance_lock:
        return
    try:
        if os.name != "nt":
            import fcntl
            fcntl.flock(_single_instance_lock, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _single_instance_lock.close()
    finally:
        _single_instance_lock = None

    if _instance_socket:
        try:
            _instance_socket.close()
        except Exception:
            pass
        _instance_socket = None

    try:
        lock_path.unlink()
    except Exception:
        pass


def _enforce_single_instance() -> None:
    try:
        _acquire_single_instance_lock()
    except RuntimeError as exc:
        msg = (
            "Another instance of the control panel is already running. "
            "Close the other window or wait a few seconds if it was just closed."
        )
        print(msg)
        try:
            logger.error(msg)
        except Exception:
            pass
        raise SystemExit(1) from exc


_enforce_single_instance()


def _print_startup_banner():
    """Emit a short banner before any other startup logs are printed."""
    border = "=" * 64
    cubic_banner = r"""
▄█████ ▄▄ ▄▄ ▄▄▄▄  ▄▄  ▄▄▄▄ ▄█████  ▄▄▄  ▄▄  ▄▄ ▄▄▄▄▄▄ ▄▄▄▄   ▄▄▄  ▄▄    
██     ██ ██ ██▄██ ██ ██▀▀▀ ██     ██▀██ ███▄██   ██   ██▄█▄ ██▀██ ██    
▀█████ ▀███▀ ██▄█▀ ██ ▀████ ▀█████ ▀███▀ ██ ▀██   ██   ██ ██ ▀███▀ ██▄▄▄                                                                           
    """
    process_label = Path(sys.executable).name if getattr(sys, "frozen", False) else "python"
    print(
        f"\n{border}\n"
        f"{cubic_banner}\n"
        f"   Welcome to CubicControl - Minecraft Server Manager\n"
        f"{border}\n"
        f"  Control panel is starting (PID {os.getpid()}, runner: {process_label})\n"
        f"  Waiting for services to initialise...\n"
        f"{border}\n"
    )


_print_startup_banner()

if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    base_path = sys._MEIPASS

    # Try multiple possible locations for templates/static
    possible_template_paths = [
        os.path.join(base_path, 'templates'),
        os.path.join(base_path, 'interface', 'templates'),
        os.path.join(base_path, 'src', 'interface', 'templates'),
    ]
    possible_static_paths = [
        os.path.join(base_path, 'static'),
        os.path.join(base_path, 'interface', 'static'),
        os.path.join(base_path, 'src', 'interface', 'static'),
    ]

    # Find the first existing template folder
    template_folder = None
    for path in possible_template_paths:
        if os.path.exists(path):
            template_folder = path
            break
    if not template_folder:
        template_folder = possible_template_paths[0]  # fallback
        print(f"Template folder not found, using fallback: {template_folder}")

    # Find the first existing static folder
    static_folder = None
    for path in possible_static_paths:
        if os.path.exists(path):
            static_folder = path
            break
    if not static_folder:
        static_folder = possible_static_paths[0]  # fallback
        print(f"Static folder not found, using fallback: {static_folder}")
else:
    # Running in normal Python
    here = os.path.dirname(os.path.abspath(__file__))
    template_folder = os.path.join(here, 'templates')
    static_folder = os.path.join(here, 'static')


app = Flask(
    __name__,
    template_folder=template_folder,
    static_folder=static_folder,
)

# Secret key for sessions
app.secret_key = secrets.token_hex(32)

# Initialize auth handler
auth_handler = AuthHandler()
secret_store = SecretStore()
caddy_manager = CaddyManager()
caddy_available_on_boot = caddy_manager.is_available()


def _sync_auth_keys_from_store() -> None:
    """Load persisted auth keys into settings/env for reuse."""
    admin_key, auth_key = secret_store.get_keys()
    settings.apply_auth_keys(admin_key, auth_key)
    if admin_key:
        os.environ["ADMIN_AUTH_KEY"] = admin_key
    if auth_key:
        os.environ["AUTHKEY_SERVER_WEBSITE"] = auth_key


_sync_auth_keys_from_store()

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

PUBLIC_REMOTE_PATHS = {
    "/status",
    "/api/server/status",
    "/start",
    "/api/server/start",
    "/stop",
    "/api/server/stop",
    "/restart",
    "/api/server/restart",
}

KEY_SETUP_SAFE_PATHS = {
    "/",
    "/login",
    "/auth/login",
    "/auth/logout",
    "/auth/status",
    "/auth/setup",
    "/api/auth-keys",
    "/api/auth-keys/status",
}

STATUS_RESPONSES = {
    "fully_loaded": ("Server Machine is live!\nMinecraft Server is RUNNING", 200),
    "starting": ("Server Machine is live!\nMinecraft Server is STARTING", 205),
    "off": ("Server Machine is live!\nMinecraft Server is OFFLINE", 206),
    "restarting": ("Server Machine is live!\nMinecraft Server is RESTARTING", 207),
    "stopping": ("Server Machine is live!\nMinecraft Server is STOPPING", 208),
    "error": ("Server Machine is OFFLINE", 500),
}


def _authorized_for_public_api() -> bool:
    """Allow bearer token access for lightweight remote control endpoints."""
    admin_key, auth_key = secret_store.get_keys()
    provided = request.headers.get("Authorization", "")
    tokens = [auth_key, admin_key]
    return any(provided == f"Bearer {token}" for token in tokens if token)


@app.before_request
def _check_authentication():
    """Check if user is authenticated before allowing access to protected routes."""
    # Allow access to auth-related routes
    if request.path in ['/auth/login', '/auth/setup', '/auth/status', '/login']:
        return None

    # Allow access to static files
    if request.path.startswith('/static/'):
        return None

    # Allow token-only access to the lightweight remote API
    if request.path in PUBLIC_REMOTE_PATHS:
        if _authorized_for_public_api():
            return None
        return jsonify({'error': 'Unauthorized'}), 403

    # Check if user is logged in
    if not session.get('authenticated'):
        # For API/AJAX requests, return 401
        if request.path.startswith('/api/') or request.path.startswith('/socket.io'):
            return jsonify({'error': 'Unauthorized - Please login'}), 401
        # For page requests, redirect to login
        return redirect(url_for('login'))

    if session.get("authenticated") and not secret_store.has_keys():
        # Block access to everything except the key setup endpoints until keys are configured
        if request.path not in KEY_SETUP_SAFE_PATHS and not request.path.startswith("/static/"):
            if request.path.startswith("/api/") or request.path.startswith("/socket.io"):
                return jsonify({'error': 'AUTH_KEYS_REQUIRED'}), 428
            return redirect(url_for('index'))

    # Additional API auth check if ADMIN_AUTH_KEY is set (for external API access)
    if request.path.startswith('/api/'):
        expected, _ = secret_store.get_keys()
        if expected:
            provided = request.headers.get('Authorization', '')
            if provided and provided != f'Bearer {expected}':
                return jsonify({'error': 'Unauthorized'}), 403

    return None

store = ServerProfileStore()
controllers: Dict[str, ServerController] = {}
controller_threads: Dict[str, Thread] = {}
server_processes: Dict[str, subprocess.Popen] = {}
server_log_threads: Dict[str, Thread] = {}
server_log_buffers: Dict[str, List[str]] = {}
playit_process: Optional[subprocess.Popen] = None
public_is_restarting = False
public_is_stopping = False
public_is_stopping_since: Optional[float] = None


# ---------- Helpers ----------
def _validated_server_path(raw_path: str) -> str:
    if not raw_path or not str(raw_path).strip():
        raise ValueError("Server folder is required and cannot be empty.")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("Server folder must be an absolute path (e.g. C:/Servers/Vanilla or /srv/mc/vanilla).")
    if path.exists() and not path.is_dir():
        raise ValueError("Server folder must refer to a directory, not a file.")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unable to create or access the server folder: {exc}") from exc
    return str(path)


def _validated_playit_path(raw_path: str) -> str:
    if not raw_path or not str(raw_path).strip():
        raise ValueError("Path to Playit.exe is required.")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("Playit.exe path must be absolute.")

    # If a directory is provided, look for playit.exe inside it
    if path.is_dir():
        path = path / "playit.exe"

    if not path.exists() or not path.is_file():
        raise ValueError("Playit.exe path must point to an existing file.")

    return str(path)


def _ensure_server_properties_exists(server_path: Path) -> None:
    server_properties_path = server_path / "server.properties"
    if not server_properties_path.exists():
        raise ValueError(
            "server.properties not found in the server folder. Please run the server once to generate it before saving."
        )


def _generate_rcon_password(existing: Optional[str]) -> str:
    if existing:
        return existing
    return secrets.token_urlsafe(16)


def _profile_from_request(data: Dict) -> ServerProfile:
    sleep_flag = data.get("pc_sleep_after_inactivity", True)
    if not isinstance(sleep_flag, bool):
        sleep_flag = str(sleep_flag).strip().lower() in {"1", "true", "yes", "on"}

    shutdown_app_flag = data.get("shutdown_app_after_inactivity", True)
    if not isinstance(shutdown_app_flag, bool):
        shutdown_app_flag = str(shutdown_app_flag).strip().lower() in {"1", "true", "yes", "on"}

    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Profile name is required.")

    existing_profile = store.get_profile(name)
    server_path = Path(_validated_server_path(data.get("server_path", "")))
    _ensure_server_properties_exists(server_path)

    rcon_password = _generate_rcon_password(existing_profile.rcon_password if existing_profile else None)

    return ServerProfile(
        name=name,
        server_path=str(server_path),
        server_ip="localhost",  # Always use localhost, not user-configurable
        run_script=(data.get("run_script") or "run.bat").strip(),
        rcon_password=rcon_password,
        rcon_port=settings.RCON_PORT,
        query_port=settings.QUERY_PORT,
        inactivity_limit=int(data.get("inactivity_limit", 1800)),
        polling_interval=int(data.get("polling_interval", 60)),
        pc_sleep_after_inactivity=sleep_flag,
        shutdown_app_after_inactivity=shutdown_app_flag,
        description=data.get("description", ""),
        env_scope=data.get("env_scope", "per_server"),
    )


def _enforce_rcon_defaults(profile: ServerProfile) -> ServerProfile:
    updated = False
    if profile.rcon_port != settings.RCON_PORT:
        profile.rcon_port = settings.RCON_PORT
        updated = True
    if profile.query_port != settings.QUERY_PORT:
        profile.query_port = settings.QUERY_PORT
        updated = True
    if not profile.rcon_password:
        profile.rcon_password = _generate_rcon_password(None)
        updated = True

    if updated:
        store.upsert_profile(profile)
    return profile


def _apply_profile_environment(profile: ServerProfile) -> None:
    """Set process env vars to match the selected profile."""
    admin_key, auth_key = secret_store.get_keys()
    os.environ["RCON_PASSWORD"] = profile.rcon_password
    os.environ["QUERY_PORT"] = str(profile.query_port)
    os.environ["RCON_PORT"] = str(profile.rcon_port)
    if admin_key:
        os.environ["ADMIN_AUTH_KEY"] = admin_key
    if auth_key:
        os.environ["AUTHKEY_SERVER_WEBSITE"] = auth_key


def _is_api_running(profile: Optional[ServerProfile]) -> bool:
    """The remote API now lives inside this control panel process and is always on."""
    return True


def _playit_path() -> str:
    handler = ConfigFileHandler()
    try:
        path = handler.get_value("Playit location", allow_empty=True).strip()
        if path:
            return path

        # Backward compatibility with older config keys
        return handler.get_value("PlayitGG location", allow_empty=True).strip()
    except Exception:
        return ""


def _is_playit_configured() -> bool:
    return bool(_playit_path())


def _is_playit_running() -> bool:
    global playit_process
    return bool(playit_process and playit_process.poll() is None)


def _start_playit_process(path: Optional[str] = None) -> bool:
    global playit_process
    if _is_playit_running():
        return False

    exe_path = path or _playit_path()
    if not exe_path:
        raise ValueError("Path to Playit.exe is not configured.")

    validated_path = _validated_playit_path(exe_path)
    env = os.environ.copy()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    playit_process = subprocess.Popen(
        [validated_path],
        cwd=str(Path(validated_path).parent),
        env=env,
        creationflags=creationflags
    )
    logger.info("Playit.exe STARTED with PID %s", playit_process.pid)
    return True


def _stop_playit_process() -> bool:
    global playit_process
    if not _is_playit_running():
        playit_process = None
        return False

    playit_process.terminate()
    try:
        playit_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        playit_process.kill()
    finally:
        logger.info("Playit process STOPPED for PID %s", playit_process.pid)
        playit_process = None
    playit_process = None
    return True


def _controller_running(name: str) -> bool:
    thread = controller_threads.get(name)
    return bool(thread and thread.is_alive())


def _start_controller(profile: ServerProfile) -> bool:
    if _controller_running(profile.name):
        return False
    controller = ServerController(profile, shutdown_callback=lambda reason="inactivity": cleanup_on_exit(reason))
    controllers[profile.name] = controller
    thread = controller.start_in_thread()
    controller_threads[profile.name] = thread
    logger.info("Controller STARTED for profile '%s'", profile.name)
    return True


def _stop_controller(name: str) -> bool:
    controller = controllers.get(name)
    if controller:
        controller.stop_controller()
    thread = controller_threads.get(name)
    if thread and thread.is_alive():
        thread.join(timeout=2)
    stopped = name in controllers
    controllers.pop(name, None)
    controller_threads.pop(name, None)
    if stopped:
        logger.info("Controller STOPPED for profile '%s'", name)
    return stopped


def _stop_services(profile: Optional[ServerProfile], *, stop_server: bool = False) -> None:
    """Stop controller and optionally the server for the given profile."""
    if not profile:
        return
    _stop_controller(profile.name)
    if stop_server:
        _stop_server_process(profile)


def _is_caddy_running() -> bool:
    return caddy_manager.is_running()


def _ensure_caddy_running(probe_for_errors: bool = False, probe_timeout: float = 3.0) -> bool:
    """Ensure Caddy is installed and running before other services."""
    if _is_caddy_running():
        # Clear stale error markers if we are already up
        caddy_manager._last_start_errors = []
        caddy_manager._last_start_exit_code = None
        caddy_manager._last_start_log_tail = []
        caddy_manager._last_start_had_failure = False
        return True
    try:
        started = caddy_manager.start(probe_for_errors=probe_for_errors, probe_timeout=probe_timeout)
        return started or _is_caddy_running()
    except Exception as exc:
        logger.warning("Unable to start Caddy automatically: %s", exc)
        return False


def _stop_caddy() -> bool:
    if not _is_caddy_running():
        return False
    return caddy_manager.stop()


def _ensure_playit_running() -> None:
    if not _is_playit_configured():
        return
    if _is_playit_running():
        return
    try:
        _start_playit_process()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to start Playit.exe automatically: %s", exc)


def _ensure_services_running(profile: Optional[ServerProfile]) -> None:
    if not profile:
        return
    profile = _enforce_rcon_defaults(profile)
    profile.ensure_scaffold()
    profile.sync_server_properties()
    _apply_profile_environment(profile)
    if not _controller_running(profile.name):
        _start_controller(profile)


def _is_server_running(profile_name: str) -> bool:
    """Check if the Minecraft server process is running."""
    proc = server_processes.get(profile_name)
    return proc is not None and proc.poll() is None


def _query_server_online(profile: ServerProfile) -> bool:
    """Return True if the server responds to a query ping."""
    try:
        JavaServer(profile.server_ip, profile.query_port).query()
        return True
    except Exception:
        return False


def _server_state(profile: Optional[ServerProfile]) -> Dict[str, object]:
    if not profile:
        return {"state": "inactive", "running": False, "starting": False}

    if _query_server_online(profile):
        return {"state": "running", "running": True, "starting": False}

    if _is_server_running(profile.name):
        return {"state": "starting", "running": False, "starting": True}

    return {"state": "stopped", "running": False, "starting": False}


def _public_status_key(profile: Optional[ServerProfile]) -> str:
    """Return a status key compatible with the legacy lightweight API."""
    global public_is_restarting, public_is_stopping, public_is_stopping_since

    state = _server_state(profile)

    if public_is_restarting:
        if state.get("state") == "running":
            public_is_restarting = False
            return "fully_loaded"
        return "restarting"

    if public_is_stopping:
        if state.get("state") in {"stopped", "inactive"}:
            public_is_stopping = False
            public_is_stopping_since = None
            return "off"
        if public_is_stopping_since and (time.time() - public_is_stopping_since) > 45:
            public_is_stopping = False
        else:
            return "stopping"

    if state.get("state") == "running":
        return "fully_loaded"
    if state.get("state") == "starting":
        return "starting"
    if state.get("state") in {"stopped", "inactive"}:
        return "off"
    return "error"


def _public_status_message(profile: Optional[ServerProfile]) -> tuple[str, int]:
    key = _public_status_key(profile)
    return STATUS_RESPONSES.get(key, STATUS_RESPONSES["error"])


def _public_status_payload(profile: Optional[ServerProfile]) -> Dict[str, object]:
    message, status_code = _public_status_message(profile)
    return {"status": message, "status_code": status_code}


def _emit_public_status(profile: Optional[ServerProfile]) -> None:
    """Emit status updates to any connected socket.io listeners."""
    try:
        socketio.emit("status_update", _public_status_payload(profile))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Unable to emit status update: %s", exc)


def _log_room(profile_name: str) -> str:
    return f"log-stream::{profile_name}"

def _append_server_log(profile_name: str, line: str) -> None:
    buffer = server_log_buffers.setdefault(profile_name, [])
    buffer.append(line)
    if len(buffer) > 400:
        server_log_buffers[profile_name] = buffer[-400:]


def _stream_server_output(profile_name: str, proc: subprocess.Popen) -> None:
    stdout = proc.stdout
    if not stdout:
        return

    try:
        stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    for raw_line in iter(stdout.readline, ""):
        if raw_line is None:
            break
        line = raw_line.rstrip("\r\n")
        _append_server_log(profile_name, line)
        # Emit to all connected clients
        try:
            socketio.emit(
                "log_line",
                {"message": line, "profile": profile_name, "source": "server"},
                namespace='/',
                room=_log_room(profile_name),
            )
            socketio.sleep(0)
        except Exception as e:
            logger.error(f"Error emitting log line: {e}")
    proc.wait()


def _start_server_process(profile: ServerProfile) -> bool:
    """Start the Minecraft server using the run script."""
    if _is_server_running(profile.name):
        logger.info(f"Server already running for profile '{profile.name}'")
        return False

    run_script_path = profile.root / profile.run_script
    if not run_script_path.exists():
        logger.error(f"Run script not found: {run_script_path}")
        raise FileNotFoundError(f"Run script not found: {run_script_path}")

    logger.info(f"Starting Minecraft server for profile '{profile.name}'")

    # Start the server process
    proc = subprocess.Popen(
        [str(run_script_path)],
        cwd=str(profile.root),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    server_processes[profile.name] = proc
    server_log_buffers.pop(profile.name, None)
    thread = socketio.start_background_task(_stream_server_output, profile.name, proc)
    server_log_threads[profile.name] = thread
    logger.info(f"Server STARTED with PID {proc.pid}")
    return True


def _stop_server_process(profile: ServerProfile) -> bool:
    """Stop the Minecraft server process."""
    stop_attempted = False

    # Try graceful shutdown via RCON regardless of local handle availability
    try:
        from mcrcon import MCRcon
        with MCRcon(profile.server_ip, profile.rcon_password, port=profile.rcon_port) as mcr:
            mcr.command("stop")
            stop_attempted = True
            logger.info(f"Sent RCON stop command to profile '{profile.name}'")
    except Exception as exc:
        logger.warning(f"Failed to send RCON stop command: {exc}")

    # Wait for graceful shutdown, then force if necessary when we own the process
    proc = server_processes.get(profile.name)
    if proc:
        try:
            proc.wait(timeout=15)
            logger.info(f"Server STOPPED gracefully for profile '{profile.name}'")
        except subprocess.TimeoutExpired:
            logger.warning("Server did not stop gracefully, terminating process")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        server_processes.pop(profile.name, None)
        server_log_threads.pop(profile.name, None)

    # If we don't have a local handle or RCON failed, poll the query port to confirm shutdown
    for _ in range(20):
        if not _query_server_online(profile) and not _is_server_running(profile.name):
            return True
        time.sleep(1)

    logger.warning(f"Unable to confirm server stop for profile '{profile.name}'")
    return stop_attempted


def _kill_process_tree(pid: int) -> bool:
    """Kill a process and all its children recursively."""
    import psutil
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                logger.info(f"Killing child process PID: {child.pid}")
                child.kill()
            except Exception as exc:
                logger.warning(f"Failed to kill child PID {child.pid}: {exc}")
        parent.kill()
        logger.info(f"Killed process tree for PID: {pid}")
        return True
    except Exception as exc:
        logger.error(f"Error killing process tree for PID {pid}: {exc}")
        return False


def _kill_by_window_title(title: str) -> bool:
    """Find windows by title and kill their process trees."""
    import pygetwindow as gw
    import win32process
    killed = False
    try:
        windows = gw.getWindowsWithTitle(title)
        for window in windows:
            try:
                _, pid = win32process.GetWindowThreadProcessId(window._hWnd)
                if _kill_process_tree(pid):
                    killed = True
            except Exception as exc:
                logger.warning(f"Failed to kill window process: {exc}")
    except Exception as exc:
        logger.warning(f"Failed to find window '{title}': {exc}")
    return killed


def _force_stop_server_process(profile: ServerProfile) -> bool:
    """Force stop the Minecraft server immediately, killing run.bat and all child processes (Java server)."""
    proc = server_processes.get(profile.name)
    killed = False
    if proc:
        logger.info(f"Force stopping server process for profile '{profile.name}' (PID: {proc.pid})")
        killed = _kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        server_processes.pop(profile.name, None)
        server_log_threads.pop(profile.name, None)
    if not killed:
        killed = _kill_by_window_title('MinecraftServer')
    return bool(killed)


def _send_profile_command(profile: ServerProfile, command: str) -> str:
    if not command.strip():
        raise ValueError("Command cannot be empty")

    with MCRcon(profile.server_ip, profile.rcon_password, port=profile.rcon_port) as mcr:
        return mcr.command(command)




# ---------- Public Remote API (token-only) ----------
def _active_profile_or_error():
    profile = store.active_profile
    if not profile:
        return None, ("No active server profile is configured", 500)
    return profile, None


@app.route("/status", methods=["GET"])
@app.route("/api/server/status", methods=["GET"])
def public_status():
    profile = store.active_profile
    message, status_code = _public_status_message(profile)
    return message, status_code


@app.route("/start", methods=["POST"])
@app.route("/api/server/start", methods=["POST"])
def public_start():
    global public_is_restarting, public_is_stopping, public_is_stopping_since
    profile, error = _active_profile_or_error()
    if error:
        return error

    status_key = _public_status_key(profile)
    if status_key in {"fully_loaded", "starting", "restarting", "stopping"}:
        return f"Server is already {status_key.replace('_', ' ')}", 400 if status_key != "stopping" else 302

    try:
        _apply_profile_environment(profile)
        _start_server_process(profile)
        public_is_restarting = False
        public_is_stopping = False
        public_is_stopping_since = None
        _emit_public_status(profile)
        return "Server is starting...", 200
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error starting server: %s", exc)
        return "Error starting server", 500


@app.route("/stop", methods=["POST"])
@app.route("/api/server/stop", methods=["POST"])
def public_stop():
    global public_is_stopping, public_is_stopping_since
    profile, error = _active_profile_or_error()
    if error:
        return error

    status_key = _public_status_key(profile)
    if status_key == "off":
        return "Server is already offline", 400
    if status_key == "starting":
        return "Processing, please wait...", 302
    if status_key == "restarting":
        return "Server is restarting, please wait...", 305
    if status_key == "stopping":
        return "Server is stopping...", 200

    def _stop_async():
        try:
            _stop_server_process(profile)
        finally:
            _emit_public_status(profile)

    public_is_stopping = True
    public_is_stopping_since = time.time()
    socketio.start_background_task(_stop_async)
    _emit_public_status(profile)
    return "Server is stopping...", 200


@app.route("/restart", methods=["POST"])
@app.route("/api/server/restart", methods=["POST"])
def public_restart():
    global public_is_restarting, public_is_stopping, public_is_stopping_since
    profile, error = _active_profile_or_error()
    if error:
        return error

    status_key = _public_status_key(profile)
    if status_key == "off":
        return "Server is already off", 400
    if status_key == "starting":
        return "Processing, please wait...", 302
    if status_key == "stopping":
        return "Server is stopping, please wait...", 305
    if public_is_restarting:
        return "Server is already restarting", 400

    def _restart_async():
        global public_is_restarting, public_is_stopping, public_is_stopping_since
        try:
            public_is_restarting = True
            _stop_server_process(profile)
            public_is_stopping = False
            public_is_stopping_since = None
            time.sleep(20)
            _start_server_process(profile)
        finally:
            public_is_restarting = False
            _emit_public_status(profile)

    public_is_restarting = True
    socketio.start_background_task(_restart_async)
    _emit_public_status(profile)
    return "Server is restarting...", 200


# ---------- Authentication Routes ----------
@app.route("/login")
def login():
    """Display the login page."""
    # If already authenticated, redirect to main page
    if session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template("login.html")


@app.route("/auth/status")
def auth_status():
    """Check if password has been set."""
    return jsonify({
        'has_password': auth_handler.has_password(),
        'has_keys': secret_store.has_keys(),
    })


@app.route("/auth/setup", methods=["POST"])
def auth_setup():
    """Set up password for first time."""
    if auth_handler.has_password():
        return jsonify({'error': 'Password already set'}), 400

    data = request.get_json()
    password = data.get('password', '').strip()

    if not password or len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400

    try:
        auth_handler.set_password(password)
        session['authenticated'] = True
        logger.info("Initial password setup completed")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to set password: {e}")
        return jsonify({'error': 'Failed to set password'}), 500


@app.route("/auth/login", methods=["POST"])
def auth_login():
    """Authenticate user."""
    data = request.get_json()
    password = data.get('password', '')

    if auth_handler.verify_password(password):
        session['authenticated'] = True
        logger.info("User logged in successfully")
        return jsonify({'success': True})
    else:
        # Include the IP address of the incoming request in the log for security auditing
        logger.warning("Failed login attempt from IP: %s", request.remote_addr)
        return jsonify({'error': 'Invalid password'}), 401


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    """Logout user."""
    session.pop('authenticated', None)
    logger.info("User logged out")
    return jsonify({'success': True})


@app.route("/api/auth-keys/status")
def auth_keys_status():
    """Return whether global AUTH/ADMIN keys are configured (values included for logged-in users)."""
    admin_key, auth_key = secret_store.get_keys()
    configured = bool(admin_key and auth_key)
    response = {
        "configured": configured,
        "admin_auth_key_set": bool(admin_key),
        "auth_key_set": bool(auth_key),
    }
    if session.get("authenticated"):
        response.update({"admin_auth_key": admin_key, "auth_key": auth_key})
    return jsonify(response)


@app.route("/api/auth-keys", methods=["POST"])
def set_auth_keys():
    """Persist the global ADMIN_AUTH_KEY and AUTH_KEY secrets."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(force=True) or {}
    admin_key = str(payload.get("admin_auth_key", "")).strip()
    auth_key = str(payload.get("auth_key", "")).strip()

    if not admin_key or not auth_key:
        return jsonify({"error": "Both ADMIN_AUTH_KEY and AUTH_KEY are required"}), 400

    try:
        secret_store.save_keys(admin_key, auth_key)
        _sync_auth_keys_from_store()
        logger.info("Global auth keys saved to secret store")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("Failed to persist auth keys: %s", exc)
        return jsonify({"error": "Failed to save auth keys"}), 500

    return jsonify({
        "success": True,
        "configured": True,
        "admin_auth_key": admin_key,
        "auth_key": auth_key,
    })


# ---------- Routes ----------
@app.route("/")
def index():
    admin_key, auth_key = secret_store.get_keys()
    return render_template(
        "control_panel.html",
        admin_auth_key=admin_key,
        auth_key=auth_key,
    )


@app.route("/api/status")
def api_status():
    active_profile = store.active_profile
    caddy_status = caddy_manager.status()
    return jsonify(
        {
            "message": "ServerSide control panel",
            "active_profile": store.active_profile_name,
            "profiles": [p.to_dict() for p in store.list_profiles()],
            "api_running": _is_api_running(active_profile),
            "controller_running": _controller_running(store.active_profile_name or ""),
            "server_running": _is_server_running(store.active_profile_name or "") if store.active_profile_name else False,
            "playit_running": _is_playit_running(),
            "playit_configured": _is_playit_configured(),
            "playit_path": _playit_path(),
            "caddy_running": caddy_status.get("running"),
            "caddy_available": caddy_status.get("available") or caddy_available_on_boot,
        }
    )


@app.route("/api/playit/path", methods=["POST"])
def set_playit_path():
    payload = request.get_json(force=True) or {}
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        return jsonify({"error": "Path to Playit.exe is required"}), 400

    # Validate the path before saving
    try:
        validated = _validated_playit_path(raw_path)
    except ValueError as exc:
        # Return error without stopping current instance or saving invalid path
        return jsonify({"error": str(exc)}), 400

    # Save the validated path
    ConfigFileHandler().set_value("Playit location", validated)

    # Return success - frontend will handle starting Playit if needed
    return jsonify({
        "message": "Playit path saved successfully",
        "playit_running": _is_playit_running(),
        "playit_path": validated
    })

@app.route("/api/server/state", methods=["GET"])
def server_state():
    profile = store.active_profile
    return jsonify(_server_state(profile))


@app.route('/api/profiles', methods=['GET', 'POST'])
def manage_profiles():
    if request.method == "GET":
        return jsonify([p.to_dict() for p in store.list_profiles()])

    # POST: Create profile
    payload = request.get_json(force=True)
    try:
        profile = _profile_from_request(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    was_active = store.active_profile_name == profile.name
    store.upsert_profile(profile)
    if was_active:
        _ensure_services_running(profile)
    return jsonify(profile.to_dict()), 201



@app.route("/api/profiles/<name>", methods=["PUT"])
def update_profile(name: str):
    if not store.get_profile(name):
        return jsonify({"error": "Profile not found"}), 404

    payload = request.get_json(force=True)
    payload = payload or {}
    payload["name"] = name
    try:
        profile = _profile_from_request(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    store.upsert_profile(profile)
    if store.active_profile_name == profile.name:
        _ensure_services_running(profile)
    return jsonify(profile.to_dict())


@app.route("/api/profiles/<name>", methods=["GET", "DELETE"])
def profile_detail(name: str):
    profile = store.get_profile(name)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if request.method == "GET":
        return jsonify(profile.to_dict())

    if store.active_profile_name == name:
        _stop_services(profile, stop_server=True)
    store.delete_profile(name)
    return jsonify({"message": f"Profile '{name}' deleted"})


@app.route("/api/profiles/<name>/activate", methods=["POST"])
def set_active(name: str):
    payload = request.get_json(silent=True) or {}
    force_restart = bool(payload.get("force_restart"))

    previous_profile = store.active_profile
    if previous_profile and previous_profile.name == name and not force_restart:
        return jsonify({"error": "Profile is already active"}), 400

    # If forcing a restart on the same profile, reuse the active profile instance; otherwise, switch normally
    profile = previous_profile if previous_profile and previous_profile.name == name else store.set_active(name)

    if force_restart and previous_profile and previous_profile.name == name:
        logger.info("Restarting services for active profile '%s'", name)
    else:
        logger.info("Activating profile '%s' (previous: %s)", name, previous_profile.name if previous_profile else "None")

    _stop_services(previous_profile, stop_server=True)
    _apply_profile_environment(profile)
    _ensure_services_running(profile)

    logger.info("Profile '%s' activated successfully", name)
    return jsonify(profile.to_dict())


@app.route("/api/profiles/<name>/properties", methods=["GET", "PUT"])
def manage_properties(name: str):
    if request.method == "GET":
        props = store.read_properties(name)
        return jsonify(props)

    payload = request.get_json(force=True) or {}
    updated = store.update_properties(name, {str(k): str(v) for k, v in payload.items()})
    return jsonify(updated)


@app.route("/api/active")
def active_profile():
    profile = store.active_profile
    if not profile:
        return jsonify({"active": None}), 404
    return jsonify(profile.to_dict())


@app.route("/api/start/controller", methods=["POST"])
def start_controller():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    if _controller_running(profile.name):
        return jsonify({"message": "Controller already running", "profile": profile.name})

    _start_controller(profile)
    return jsonify({"message": "Controller started", "profile": profile.name})


@app.route("/api/start/server", methods=["POST"])
def start_server():
    """Start the Minecraft server for the active profile."""
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    state = _server_state(profile)
    if state.get("state") in {"starting", "running"}:
        return jsonify({"error": "Server is already running"}), 400

    try:
        _start_server_process(profile)
        return jsonify({"message": f"Server starting for profile '{profile.name}'"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/start/caddy", methods=["POST"])
def start_caddy():
    try:
        started = caddy_manager.start()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    message = "Caddy started" if started else "Caddy already running"
    status = caddy_manager.status()
    return jsonify({"message": message, "running": status.get("running"), "pid": status.get("pid")})


@app.route("/api/start/playit", methods=["POST"])
def start_playit():
    path = _playit_path()
    if not path:
        return jsonify({"error": "No path is defined for Playit.exe", "require_path": True}), 400

    if _is_playit_running():
        return jsonify({"error": "Playit is already running"}), 400

    try:
        started = _start_playit_process(path)
    except ValueError as exc:
        return jsonify({"error": str(exc), "require_path": True}), 400
    except Exception as exc:  # pragma: no cover - defensive guard
        return jsonify({"error": str(exc)}), 500

    message = "Playit started" if started else "Playit already running"
    return jsonify({"message": message, "running": _is_playit_running()})


@app.route("/api/stop/controller", methods=["POST"])
def stop_controller():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    if _stop_controller(profile.name):
        return jsonify({"message": "Controller stopped"})
    return jsonify({"error": "Controller is not running"}), 400


@app.route("/api/stop/caddy", methods=["POST"])
def stop_caddy():
    if not _is_caddy_running():
        return jsonify({"error": "Caddy is already stopped"}), 400

    if _stop_caddy():
        return jsonify({"message": "Caddy stopped"})

    return jsonify({"error": "Failed to stop Caddy"}), 500


@app.route("/api/stop/playit", methods=["POST"])
def stop_playit():
    if not _playit_path():
        return jsonify({"error": "No path is defined for Playit.exe", "require_path": True}), 400

    if not _is_playit_running():
        return jsonify({"error": "Playit is already stopped"}), 400

    if _stop_playit_process():
        return jsonify({"message": "Playit stopped"})

    return jsonify({"error": "Playit is not running"}), 400


@app.route("/api/stop/server", methods=["POST"])
def stop_server():
    """Stop the Minecraft server for the active profile."""
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    state = _server_state(profile)
    if state.get("state") in {"stopped", "inactive"}:
        return jsonify({"error": "Server is not running"}), 400

    def _stop_async():
        try:
            _stop_server_process(profile)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to stop server for profile '%s': %s", profile.name, exc)

    socketio.start_background_task(_stop_async)
    return jsonify({"message": f"Stopping server for profile '{profile.name}'"})


@app.route("/api/stop/server/force", methods=["POST"])
def force_stop_server():
    """Force stop the Minecraft server immediately without graceful shutdown."""
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    def _force_stop_async():
        try:
            _force_stop_server_process(profile)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to force stop server for profile '%s': %s", profile.name, exc)

    socketio.start_background_task(_force_stop_async)
    return jsonify({"message": f"Force stopping server for profile '{profile.name}'"})


@app.route("/api/server/command", methods=["POST"])
def send_command():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    payload = request.get_json(force=True) or {}
    command = str(payload.get("command", "")).strip()
    if not command:
        return jsonify({"error": "Command cannot be empty"}), 400

    state = _server_state(profile)
    if state.get("state") != "running":
        return jsonify({"error": "Server is not running"}), 400

    try:
        output = _send_profile_command(profile, command)

        # Emit command and response to live logs
        socketio.emit(
            "log_line",
            {"message": f"> {command}", "profile": profile.name, "source": "command"},
            namespace='/',
            room=_log_room(profile.name),
        )
        if output:
            socketio.emit(
                "log_line",
                {"message": output, "profile": profile.name, "source": "command_response"},
                namespace='/',
                room=_log_room(profile.name),
            )

        return jsonify({"message": output or "Command sent"})
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("Failed to send command via RCON: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/logs/<name>")
def read_logs(name: str):
    profile = store.get_profile(name)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    if _is_server_running(profile.name) and server_log_buffers.get(profile.name):
        return jsonify({"log_file": "live:process", "lines": server_log_buffers.get(profile.name, [])[-200:]})

    latest_log = profile.root / "logs" / "latest.log"
    if latest_log.exists():
        tail = latest_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
        return jsonify({"log_file": str(latest_log), "lines": tail})

    return jsonify({"logs": [], "message": "No server logs available yet"})


# ---------- Socket log streaming ----------
@socketio.on("follow_logs")
def follow_logs(payload):
    # Always stream the active profile; ignore client-provided profile names to avoid mismatched log views
    profile = store.active_profile
    if not profile:
        emit("log_line", {"message": "No active profile"})
        return

    logger.info(f"Client connected to follow logs for profile: {profile.name}")

    room = _log_room(profile.name)
    join_room(room)

    # Send buffered logs line by line
    for line in server_log_buffers.get(profile.name, [])[-200:]:
        emit("log_line", {"message": line}, room=room)

    # If server is not running, send static log file
    latest_log = profile.root / "logs" / "latest.log"
    if not _is_server_running(profile.name) and latest_log.exists():
        for line in latest_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]:
            emit("log_line", {"message": line}, room=room)


@app.route("/api/test/socket", methods=["POST"])
def test_socket():
    """Test endpoint to verify socket emissions are working"""
    try:
        socketio.emit("log_line", {"message": "TEST MESSAGE FROM SERVER", "profile": "test", "source": "test"}, namespace='/')
        return jsonify({"message": "Test emission sent"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def initialize_services(probe_caddy_errors: bool = False, probe_timeout: float = 45.0) -> tuple[bool, Dict[str, object]]:
    """Initialize services on startup. Caddy starts first, then other services."""
    _ensure_caddy_running(probe_for_errors=probe_caddy_errors, probe_timeout=probe_timeout)
    status = caddy_manager.status()
    if not status.get("running") or status.get("last_start_had_failure") or status.get("last_start_errors"):
        return False, status

    _ensure_playit_running()
    _ensure_services_running(store.active_profile)
    return True, status


def _log_startup_abort(status: Dict[str, object]) -> None:
    """Log a single abort message with the best available snippet."""
    _log_caddy_startup_diagnostics(status)
    log_path = status.get("log_path") or "logs/caddy.log"
    logger.error("Startup aborted because Caddy did not start cleanly. Check %s for details.", log_path)


def _log_caddy_startup_diagnostics(status: Dict[str, object]) -> None:
    """Emit a concise console message when Caddy emits errors on startup."""
    log_path = status.get("log_path") or "logs/caddy.log"
    error_lines = status.get("last_start_errors") or []
    log_tail = status.get("last_start_log_tail") or []
    exit_code = status.get("last_start_exit_code")
    running = status.get("running")
    had_failure = status.get("last_start_had_failure")

    if error_lines or had_failure:
        snippet_source = log_tail if log_tail else error_lines
        snippet = "\n".join(snippet_source[-5:])
        logger.error("Caddy reported startup errors. Check %s for details:\n%s", log_path, snippet)
    elif exit_code is not None and not running:
        logger.error("Caddy exited during startup (code %s). Check %s for details.", exit_code, log_path)
    elif not running:
        logger.error("Caddy is not running after startup. Check %s for details.", log_path)

def wait_for_server(url, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def open_browser_when_ready():
    url = "http://localhost:38000"
    if wait_for_server(url):
        webbrowser.open(url)

_shutdown_in_progress = False


def cleanup_on_exit(reason: str = "shutdown"):
    """Cleanup function called when application exits"""
    global _shutdown_in_progress
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True

    logger.info("Application shutting down (%s), cleaning up...", reason)
    profile = store.active_profile

    try:
        _stop_services(profile, stop_server=True)
    except Exception as exc:
        logger.warning("Failed to stop services during shutdown: %s", exc)

    try:
        _stop_playit_process()
    except Exception as exc:
        logger.warning("Failed to stop Playit.exe during shutdown: %s", exc)

    try:
        _stop_caddy()
    except Exception as exc:
        logger.warning("Failed to stop Caddy during shutdown: %s", exc)

    _release_single_instance_lock()


def _handle_exit_signal(signum):
    logger.info("Received termination signal (%s); shutting down.", signum)
    cleanup_on_exit(reason=f"signal {signum}")
    sys.exit(0)


def _register_signal_handlers():
    signals = [signal.SIGINT, getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)]
    for sig in signals:
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_exit_signal)
        except Exception:
            pass

    # Windows console close (clicking the X in cmd)
    try:
        import win32api

        def _console_ctrl_handler(event):
            logger.info("Console close event received (%s); shutting down.", event)
            cleanup_on_exit(reason=f"console event {event}")
            return True

        win32api.SetConsoleCtrlHandler(_console_ctrl_handler, True)
    except Exception:
        pass


_register_signal_handlers()
atexit.register(cleanup_on_exit)


def main():
    """Entry point for running the control panel."""
    logger.info("Starting CubicControl")
    logger.info("Caddy is starting, please wait...")
    services_started, caddy_status = initialize_services(probe_caddy_errors=True, probe_timeout=3.0)
    if not services_started:
        _log_startup_abort(caddy_status)
        try:
            # Ensure the prompt appears on its own line after any error logs
            print("\nPress a key to exit...", flush=True)
            input()
        except Exception:
            pass
        return
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    logger.info("Starting control panel UI")
    socketio.run(app, host="0.0.0.0", port=38000, allow_unsafe_werkzeug=True, debug=False)


if __name__ == "__main__":
    main()
