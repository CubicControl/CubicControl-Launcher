# Control panel overview

This control panel is a local Flask + Socket.IO interface that wraps the existing API (`src/api/server_app.py`) and the background controller logic. It is designed to run on machine wake so you can manage multiple server or modpack installs from one dashboard.

## Concepts
- **Server profiles** – Each Minecraft install is stored as a profile with its own folder, ports, RCON password, and shutdown/auth keys.
- **Scaffolding** – Creating or bootstrapping a profile makes a minimal folder with `run.bat`, `server.properties`, and `ControllerLogs/` for convenience. Drop your `server.jar` next to `run.bat` and run it once so Minecraft can expand the rest of the files.
- **Environment scope** – Credentials and ports are stored per profile. Activating a profile writes the `Run.bat location` to `ServerConfig.ini` for backward compatibility and exports the matching environment variables before launching the API or controller.

## Endpoints
- `GET /` – Basic health/readiness with the active profile name.
- `GET|POST /api/profiles` – List or create server profiles.
- `POST /api/profiles/<name>/activate` – Make a profile the active one and sync config/env vars.
- `GET|PUT /api/profiles/<name>/properties` – Read or update `server.properties` within the profile folder.
- `POST /api/profiles/<name>/bootstrap` – Create the folder scaffold for uploads and logging.
- `GET /api/active` – Details for the active profile.
- `POST /api/start/api` – Launch the existing Flask Socket.IO API with the active profile environment.
- `POST /api/start/controller` – Start the background inactivity controller for the active profile.
- `GET /api/logs/<name>` – Tail the most recent controller log file.
- `SocketIO follow_logs` – Stream live log lines for the active profile.

## Starting the interface
Run the control panel locally (for example via Task Scheduler on wake):

```bash
python -m src.interface.control_panel
```

By default it listens on port `38000`. You can adjust the host/port directly inside `src/interface/control_panel.py` if you need a different binding.
