import os
import subprocess
import sys
from pathlib import Path
from threading import Thread
from typing import Dict, Optional

import requests

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from src.config.config_file_handler import ConfigFileHandler
from src.controller.server_controller import ServerController
from src.interface.server_profiles import ServerProfile, ServerProfileStore
from src.logging_utils.logger import logger

APP_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
socketio = SocketIO(app, cors_allowed_origins="*")

store = ServerProfileStore()
controllers: Dict[str, ServerController] = {}
controller_threads: Dict[str, Thread] = {}
api_process: Optional[subprocess.Popen] = None
server_processes: Dict[str, subprocess.Popen] = {}


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


def _profile_from_request(data: Dict) -> ServerProfile:
    sleep_flag = data.get("pc_sleep_after_inactivity", True)
    if not isinstance(sleep_flag, bool):
        sleep_flag = str(sleep_flag).strip().lower() in {"1", "true", "yes", "on"}

    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Profile name is required.")

    return ServerProfile(
        name=name,
        server_path=_validated_server_path(data.get("server_path", "")),
        server_ip=data.get("server_ip", "localhost"),
        run_script=(data.get("run_script") or "run.bat").strip(),
        rcon_password=data.get("rcon_password", ""),
        rcon_port=int(data.get("rcon_port", 27001)),
        query_port=int(data.get("query_port", 27002)),
        auth_key=data.get("auth_key", ""),
        shutdown_key=data.get("shutdown_key", ""),
        inactivity_limit=int(data.get("inactivity_limit", 1800)),
        polling_interval=int(data.get("polling_interval", 60)),
        pc_sleep_after_inactivity=sleep_flag,
        description=data.get("description", ""),
        env_scope=data.get("env_scope", "per_server"),
    )


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


def _ensure_services_running(profile: Optional[ServerProfile]) -> None:
    if not profile:
        return
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
        stderr=subprocess.PIPE,
    )

    server_processes[profile.name] = proc
    logger.info(f"Server started with PID {proc.pid}")
    return True


def _stop_server_process(profile: ServerProfile) -> bool:
    """Stop the Minecraft server process."""
    if not _is_server_running(profile.name):
        logger.info(f"Server not running for profile '{profile.name}'")
        return False

    # Try graceful shutdown via controller first
    controller = controllers.get(profile.name)
    if controller:
        controller.stop_minecraft_server()

    # Terminate the process
    proc = server_processes.get(profile.name)
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info(f"Server process stopped for profile '{profile.name}'")
        server_processes.pop(profile.name, None)
        return True

    return False


# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("control_panel.html")


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
        }
    )


@app.route("/api/profiles", methods=["GET", "POST"])
def profiles():
    if request.method == "GET":
        return jsonify([p.to_dict() for p in store.list_profiles()])

    payload = request.get_json(force=True)
    try:
        profile = _profile_from_request(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    profile.ensure_scaffold()
    store.upsert_profile(profile)
    if store.active_profile_name == profile.name:
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

    _stop_controller(name)
    store.delete_profile(name)
    return jsonify({"message": f"Profile '{name}' deleted"})


@app.route("/api/profiles/<name>/activate", methods=["POST"])
def set_active(name: str):
    profile = store.set_active(name)
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


@app.route("/api/profiles/<name>/bootstrap", methods=["POST"])
def bootstrap_profile(name: str):
    profile = store.get_profile(name)
    if not profile:
        return jsonify({"error": f"Profile '{name}' not found"}), 404

    profile.ensure_scaffold()
    ConfigFileHandler().set_value('Run.bat location', str(profile.root))
    _apply_profile_environment(profile)
    return jsonify({"message": "Scaffold created", "profile": profile.to_dict()})


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

    if _is_server_running(profile.name):
        return jsonify({"message": "Server already running"})

    try:
        _start_server_process(profile)
        return jsonify({"message": f"Server starting for profile '{profile.name}'"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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


@app.route("/api/stop/server", methods=["POST"])
def stop_server():
    """Stop the Minecraft server for the active profile."""
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    if not _is_server_running(profile.name):
        return jsonify({"error": "Server is not running"}), 400

    try:
        _stop_server_process(profile)
        return jsonify({"message": f"Server stopped for profile '{profile.name}'"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/logs/<name>")
def read_logs(name: str):
    profile = store.get_profile(name)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    profile.ensure_scaffold()
    log_files = sorted(profile.controller_log_dir.glob("*_MinecraftControllerLogs.log"), reverse=True)
    if not log_files:
        return jsonify({"logs": []})
    latest = log_files[0]
    tail = latest.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
    return jsonify({"log_file": str(latest), "lines": tail})


# ---------- Socket log streaming ----------
@socketio.on("follow_logs")
def follow_logs(payload):
    name = payload.get("profile") if payload else None
    profile = store.get_profile(name or store.active_profile_name)
    if not profile:
        emit("log_line", {"message": "No profile available"})
        return

    profile.ensure_scaffold()
    log_files = sorted(profile.controller_log_dir.glob("*_MinecraftControllerLogs.log"), reverse=True)
    if not log_files:
        emit("log_line", {"message": "No log file yet"})
        return

    latest = log_files[0]

    def stream_file(path: Path):
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    emit("log_line", {"message": line.rstrip()})
                else:
                    socketio.sleep(1)

    socketio.start_background_task(stream_file, latest)


@app.before_first_request
def auto_start_services():
    _ensure_services_running(store.active_profile)


if __name__ == "__main__":
    logger.info("Starting control panel UI")
    socketio.run(app, host="0.0.0.0", port=38000, debug=False)
