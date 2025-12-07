# Control panel overview

This control panel is a local Flask + Socket.IO interface that now directly exposes the token-gated public API alongside the background controller logic. It is designed to run on machine wake so you can manage multiple server or modpack installs from one dashboard.

## Concepts
- **Server profiles** – Each Minecraft install is stored as a profile with its own folder, shutdown/auth keys, and generated RCON credentials. The folder must contain `server.properties` (meaning the server has been run at least once) before you can create a profile.
- **Environment scope** – Credentials and ports are stored per profile. Activating a profile writes the `Run.bat location` to `ServerConfig.ini` for backward compatibility and exports the matching environment variables before launching the API or controller. RCON/query ports are locked to `27001/27002`, and an internal RCON password is generated and reused automatically.

## Endpoints
- `GET /` – Basic health/readiness with the active profile name.
- `GET|POST /api/profiles` – List or create server profiles.
- `POST /api/profiles/<name>/activate` – Make a profile the active one and sync config/env vars.
- `GET|PUT /api/profiles/<name>/properties` – Read or update `server.properties` within the profile folder.
- `GET /api/active` – Details for the active profile.
- `POST /api/start/api` – Launch the existing Flask Socket.IO API with the active profile environment.
- `POST /api/start/controller` – Start the background inactivity controller for the active profile.
- `GET /api/logs/<name>` – Tail live server output (if running) or the latest Minecraft `logs/latest.log` file.
- `SocketIO follow_logs` – Stream live server log lines for the active profile.

## Starting the interface
Run the control panel locally (for example via Task Scheduler on wake):

```bash
python -m src.interface.control_panel
```

By default it listens on port `38000`. You can adjust the host/port directly inside `src/interface/control_panel.py` if you need a different binding.

### Legacy first-run GUI
`src/gui/initial_setup.py` is still present for the older Tkinter onboarding flow, but all configuration can now be handled directly in the control panel. You can skip the Tkinter helper unless you specifically want a desktop-native initial experience.
