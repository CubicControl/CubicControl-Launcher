import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit

from src.config.config_file_handler import ConfigFileHandler
from src.controller.server_controller import ServerController
from src.interface.server_profiles import ServerProfile, ServerProfileStore
from src.logging_utils.logger import logger

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

store = ServerProfileStore()
controllers: Dict[str, ServerController] = {}


# ---------- Helpers ----------
def _profile_from_request(data: Dict) -> ServerProfile:
    sleep_flag = data.get("pc_sleep_after_inactivity", True)
    if not isinstance(sleep_flag, bool):
        sleep_flag = str(sleep_flag).strip().lower() in {"1", "true", "yes", "on"}

    return ServerProfile(
        name=data["name"],
        server_path=data["server_path"],
        server_ip=data.get("server_ip", "localhost"),
        run_script=data.get("run_script", "run.bat"),
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


# ---------- Routes ----------
@app.route("/")
def index():
    return jsonify({
        "message": "ServerSide control panel",
        "active_profile": store.active_profile_name,
        "profiles": [p.to_dict() for p in store.list_profiles()],
    })


@app.route("/api/profiles", methods=["GET", "POST"])
def profiles():
    if request.method == "GET":
        return jsonify([p.to_dict() for p in store.list_profiles()])

    payload = request.get_json(force=True)
    profile = _profile_from_request(payload)
    profile.ensure_scaffold()
    store.upsert_profile(profile)
    return jsonify(profile.to_dict()), 201


@app.route("/api/profiles/<name>/activate", methods=["POST"])
def set_active(name: str):
    profile = store.set_active(name)
    ConfigFileHandler().set_value('Run.bat location', str(profile.root))
    _apply_profile_environment(profile)
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

    _apply_profile_environment(profile)
    env = os.environ.copy()
    env.update({
        "RCON_PASSWORD": profile.rcon_password,
        "AUTHKEY_SERVER_WEBSITE": profile.auth_key,
        "SHUTDOWN_AUTH_KEY": profile.shutdown_key,
        "QUERY_PORT": str(profile.query_port),
        "RCON_PORT": str(profile.rcon_port),
    })
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])

    cmd = [sys.executable, "-m", "src.api.server_app"]
    subprocess.Popen(cmd, env=env)
    return jsonify({"message": "API starting", "cmd": cmd})


@app.route("/api/start/controller", methods=["POST"])
def start_controller():
    profile = store.active_profile
    if not profile:
        return jsonify({"error": "No active profile"}), 400

    controller = ServerController(profile)
    controllers[profile.name] = controller
    controller.start_in_thread()
    return jsonify({"message": "Controller started", "profile": profile.name})


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


if __name__ == "__main__":
    logger.info("Starting control panel UI")
    socketio.run(app, host="0.0.0.0", port=38000, debug=False)
