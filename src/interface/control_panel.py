import os
import secrets
import subprocess
import sys
from pathlib import Path
from threading import Thread
from typing import Dict, List, Optional
import logging
import warnings

import time
import requests
from mcstatus import JavaServer
from mcrcon import MCRcon

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit, join_room

from src.config import settings
from src.config.config_file_handler import ConfigFileHandler
from src.controller.server_controller import ServerController
from src.interface.server_profiles import ServerProfile, ServerProfileStore
from src.logging_utils.logger import logger

APP_DIR = Path(__file__).resolve().parent

warnings.filterwarnings(
    "ignore",
    message=r"Werkzeug appears to be used in a production deployment",
)

show_server_banner = lambda *args, **kwargs: None  # hide Flask banner

for noisy in ("werkzeug", "engineio", "socketio", "flask_socketio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

@app.before_request
def _validate_web_auth():
    if request.path.startswith('/socket.io'):
        return None
    if not request.path.startswith('/api/'):
        return None

    expected = settings.AUTH_KEY
    if not expected:
        return None

    provided = request.headers.get('Authorization', '')
    if provided != f'Bearer {expected}':
        return jsonify({'error': 'Unauthorized'}), 403
    return None

store = ServerProfileStore()
controllers: Dict[str, ServerController] = {}
controller_threads: Dict[str, Thread] = {}
api_process: Optional[subprocess.Popen] = None
server_processes: Dict[str, subprocess.Popen] = {}
server_log_threads: Dict[str, Thread] = {}
server_log_buffers: Dict[str, List[str]] = {}
playit_process: Optional[subprocess.Popen] = None


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
        raise ValueError("Path to PlayitGG.exe is required.")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("PlayitGG.exe path must be absolute.")
    if not path.exists() or not path.is_file():
        raise ValueError("PlayitGG.exe path must point to an existing file.")
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
        server_ip=data.get("server_ip", "localhost"),
        run_script=(data.get("run_script") or "run.bat").strip(),
        rcon_password=rcon_password,
        rcon_port=settings.RCON_PORT,
        query_port=settings.QUERY_PORT,
        auth_key=data.get("auth_key", ""),
        shutdown_key=data.get("shutdown_key", ""),
        inactivity_limit=int(data.get("inactivity_limit", 1800)),
        polling_interval=int(data.get("polling_interval", 60)),
        pc_sleep_after_inactivity=sleep_flag,
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
    os.environ["RCON_PASSWORD"] = profile.rcon_password
    os.environ["AUTHKEY_SERVER_WEBSITE"] = profile.auth_key
    if profile.shutdown_key:
        os.environ["SHUTDOWN_AUTH_KEY"] = profile.shutdown_key
    os.environ["QUERY_PORT"] = str(profile.query_port)
    os.environ["RCON_PORT"] = str(profile.rcon_port)


def _is_api_running(profile: Optional[ServerProfile]) -> bool:
    global api_process
    if api_process and api_process.poll() is None:
        return True

    if not profile:
        return False

    headers = {"Authorization": f"Bearer {profile.auth_key}"} if profile.auth_key else {}
    try:
        resp = requests.get("http://localhost:37000/status", headers=headers, timeout=1.5)
        return resp.status_code < 500
    except requests.RequestException:
        return False


def _playit_path() -> str:
    handler = ConfigFileHandler()
    try:
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
        raise ValueError("Path to PlayitGG.exe is not configured.")

    validated_path = _validated_playit_path(exe_path)
    env = os.environ.copy()
    playit_process = subprocess.Popen([validated_path], cwd=str(Path(validated_path).parent), env=env)
    logger.info("PlayitGG started with PID %s", playit_process.pid)
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
        logger.info("PlayitGG process stopped")
    playit_process = None
    return True


def _start_api_process(profile: ServerProfile) -> bool:
    global api_process
    if _is_api_running(profile):
        return False

    _apply_profile_environment(profile)
    env = os.environ.copy()
    env.update(
        {
            "RCON_PASSWORD": profile.rcon_password,
            "AUTHKEY_SERVER_WEBSITE": profile.auth_key,
            "SHUTDOWN_AUTH_KEY": profile.shutdown_key,
            "QUERY_PORT": str(profile.query_port),
            "RCON_PORT": str(profile.rcon_port),
        }
    )
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])

    cmd = [sys.executable, "-m", "src.api.server_app"]
    api_process = subprocess.Popen(cmd, env=env)
    logger.info("API started for profile '%s' with PID %s", profile.name, api_process.pid)
    return True


def _stop_api_process(profile: Optional[ServerProfile]) -> bool:
    global api_process
    if api_process and api_process.poll() is None:
        api_process.terminate()
        try:
            api_process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive guard
            api_process.kill()
        finally:
            logger.info("API process stopped")
            api_process = None
        return True

    if profile:
        headers = {"Authorization": f"Bearer {profile.auth_key}", "shutdown-header": profile.shutdown_key}
        try:
            requests.post("http://localhost:37000/shutdown", headers=headers, timeout=2)
            return True
        except requests.RequestException:
            return False
    return False


def _controller_running(name: str) -> bool:
    thread = controller_threads.get(name)
    return bool(thread and thread.is_alive())


def _start_controller(profile: ServerProfile) -> bool:
    if _controller_running(profile.name):
        return False
    controller = ServerController(profile)
    controllers[profile.name] = controller
    thread = controller.start_in_thread()
    controller_threads[profile.name] = thread
    logger.info("Controller started for profile '%s'", profile.name)
    return True


def _stop_controller(name: str) -> bool:
    controller = controllers.get(name)
    if controller:
        controller.stop()
    thread = controller_threads.get(name)
    if thread and thread.is_alive():
        thread.join(timeout=2)
    stopped = name in controllers
    controllers.pop(name, None)
    controller_threads.pop(name, None)
    return stopped


def _stop_services(profile: Optional[ServerProfile], *, stop_server: bool = False) -> None:
    """Stop API, controller, and optionally the server for the given profile."""
    if not profile:
        return
    _stop_controller(profile.name)
    _stop_api_process(profile)
    if stop_server:
        _stop_server_process(profile)


def _ensure_playit_running() -> None:
    if not _is_playit_configured():
        return
    if _is_playit_running():
        return
    try:
        _start_playit_process()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to start PlayitGG automatically: %s", exc)


def _ensure_services_running(profile: Optional[ServerProfile]) -> None:
    if not profile:
        return
    profile = _enforce_rcon_defaults(profile)
    profile.ensure_scaffold()
    profile.sync_server_properties()
    ConfigFileHandler().set_value('Run.bat location', str(profile.root))
    _apply_profile_environment(profile)
    if not _is_api_running(profile):
        _start_api_process(profile)
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
    logger.info(f"Server started with PID {proc.pid}")
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
            logger.info(f"Server stopped gracefully for profile '{profile.name}'")
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


def _send_profile_command(profile: ServerProfile, command: str) -> str:
    if not command.strip():
        raise ValueError("Command cannot be empty")

    with MCRcon(profile.server_ip, profile.rcon_password, port=profile.rcon_port) as mcr:
        return mcr.command(command)




# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("control_panel.html", auth_key=settings.AUTH_KEY)


@app.route("/api/status")
def status():
    active_profile = store.active_profile
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
        }
    )


@app.route("/api/playit/path", methods=["POST"])
def set_playit_path():
    payload = request.get_json(force=True) or {}
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        return jsonify({"error": "Path to PlayitGG.exe is required"}), 400

    try:
        validated = _validated_playit_path(raw_path)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    ConfigFileHandler().set_value("PlayitGG location", validated)
    started = False
    try:
        started = _start_playit_process(validated)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to start PlayitGG after saving path: %s", exc)

    return jsonify({"message": "PlayitGG path saved", "playit_running": _is_playit_running(), "started": started})

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

    _stop_services(profile, stop_server=True)
    store.delete_profile(name)
    return jsonify({"message": f"Profile '{name}' deleted"})


@app.route("/api/profiles/<name>/activate", methods=["POST"])
def set_active(name: str):
    previous_profile = store.active_profile
    if previous_profile and previous_profile.name == name:
        return jsonify({"error": "Profile is already active"}), 400
    profile = store.set_active(name)
    _stop_services(previous_profile, stop_server=True)
    ConfigFileHandler().set_value('Run.bat location', str(profile.root))
    _apply_profile_environment(profile)
    _ensure_services_running(profile)
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


@app.route("/api/start/api", methods=["POST"])
def start_api():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    if _is_api_running(profile):
        return jsonify({"message": "API already running"})

    _start_api_process(profile)
    return jsonify({"message": "API starting"})


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


@app.route("/api/start/playit", methods=["POST"])
def start_playit():
    path = _playit_path()
    if not path:
        return jsonify({"error": "PlayitGG.exe path is not configured", "require_path": True}), 400

    try:
        started = _start_playit_process(path)
    except ValueError as exc:
        return jsonify({"error": str(exc), "require_path": True}), 400
    except Exception as exc:  # pragma: no cover - defensive guard
        return jsonify({"error": str(exc)}), 500

    message = "PlayitGG started" if started else "PlayitGG already running"
    return jsonify({"message": message, "running": _is_playit_running()})


@app.route("/api/stop/api", methods=["POST"])
def stop_api():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    stopped = _stop_api_process(profile)
    if stopped:
        return jsonify({"message": "API stopped"})
    return jsonify({"error": "API was not running"}), 400


@app.route("/api/stop/controller", methods=["POST"])
def stop_controller():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    if _stop_controller(profile.name):
        return jsonify({"message": "Controller stopped"})
    return jsonify({"error": "Controller was not running"}), 400


@app.route("/api/stop/playit", methods=["POST"])
def stop_playit():
    if _stop_playit_process():
        return jsonify({"message": "PlayitGG stopped"})
    return jsonify({"error": "PlayitGG was not running"}), 400


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


@app.before_first_request
def auto_start_services():
    _ensure_playit_running()
    _ensure_services_running(store.active_profile)


if __name__ == "__main__":
    logger.info("Starting control panel UI")
    socketio.run(app, host="0.0.0.0", port=38000, allow_unsafe_werkzeug=True, debug=False)
