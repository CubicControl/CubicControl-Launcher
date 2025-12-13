# CubicControl API Reference

This document summarizes the HTTP surface area exposed by the CubicControl control panel and the lightweight public API. Endpoints are grouped by how they are authenticated and whether they are intended for remote automation or the local admin panel.

## Authentication model
- **Panel password & session**: `/auth/setup` stores a hashed password locally, and `/auth/login` issues a session flag (`session['authenticated']`) that is required for all HTML routes and most `/api/` endpoints. Unauthenticated API calls receive `401` JSON responses, while browser routes redirect to `/login`.
- **Key gate for API use**: After login, most API routes also check that `ADMIN_AUTH_KEY` and `AUTH_KEY` exist in the secret store or environment. Requests are blocked with `428 AUTH_KEYS_REQUIRED` until both keys are present.
- **Bearer token (admin key)**: When the admin key is set, `/api/` requests that include an `Authorization` header must match `Bearer <ADMIN_AUTH_KEY>` or they are rejected with `403`. The bearer is optional when a valid session cookie is already present.
- **Bearer token (public key)**: The lightweight public API and select remote control routes accept `Authorization: Bearer <AUTH_KEY>`. When this header is valid, those endpoints do not require a session cookie.

## Public remote control (AUTH_KEY)
These endpoints are usable either through the standalone public API service (default port `38001`) or via the main control panel when providing `Authorization: Bearer <AUTH_KEY>`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/server/status` | Current server status (fully loaded, starting, stopping, offline). |
| POST | `/api/server/start` | Start the Minecraft server for the active profile. |
| POST | `/api/server/stop` | Gracefully stop the active server; returns 302 if already stopping. |
| POST | `/api/server/restart` | Restart the active server (stop then start). |

**Security**: All four routes require the correct `AUTH_KEY` bearer. If the key is missing, the standalone service returns `428 AUTH_KEY_REQUIRED`; the embedded routes return `403 Unauthorized` unless the caller already has a logged-in session.

## Admin panel API (session and ADMIN_AUTH_KEY)
All routes below live under `/api/` and require an authenticated session. If an `Authorization` header is supplied, it must match `ADMIN_AUTH_KEY`; otherwise the request is rejected with `403`.

### System & configuration
- `GET /api/status` – Panel health summary (active profile, service state, Playit/Caddy status).
- `POST /api/playit/path` – Save the validated location of `Playit.exe`.
- `GET /api/server/state` – Detailed state for the active server (running/starting/stopped and ports).

### Profile management
- `GET /api/profiles` – List all profiles.
- `POST /api/profiles` – Create or update a profile (server path, ports, description, environment scope).
- `PUT /api/profiles/<name>` – Update an existing profile (same payload as create).
- `GET /api/profiles/<name>` – Retrieve profile details.
- `DELETE /api/profiles/<name>` – Delete a profile (stops services if active).
- `POST /api/profiles/<name>/activate` – Set the active profile, optionally forcing service restarts.
- `GET /api/profiles/<name>/properties` – Read `server.properties` for the profile.
- `PUT /api/profiles/<name>/properties` – Write `server.properties` values.
- `GET /api/active` – Return the active profile record.

### Service control
- `POST /api/start/controller` / `/api/stop/controller` – Start or stop the background inactivity controller.
- `POST /api/start/server` / `/api/stop/server` / `/api/stop/server/force` – Manage the Minecraft server process (graceful or forced stop).
- `POST /api/start/caddy` / `/api/stop/caddy` – Control the bundled Caddy reverse proxy.
- `POST /api/start/playit` / `/api/stop/playit` – Control the Playit tunnel helper.
- `POST /api/server/command` – Send an RCON command to the running server.

### Logs & diagnostics
- `GET /api/logs/<name>` – Read recent live or file-based server logs for the specified profile.
- `POST /api/test/socket` – Emit a test log message over Socket.IO (primarily for diagnostics).

## Authentication & key setup endpoints
- `GET /auth/status` – Returns whether a password and auth keys are configured.
- `POST /auth/setup` – One-time password creation (also logs in the user).
- `POST /auth/login` / `POST /auth/logout` – Manage the session login state.
- `GET /api/auth-keys/status` – Indicates if `ADMIN_AUTH_KEY` and `AUTH_KEY` are stored; returns values when authenticated.
- `POST /api/auth-keys` – Persist both keys to the secret store (requires session).

## Security behaviors at a glance
- Unauthenticated requests to protected API routes receive JSON `401` responses; browser routes redirect to `/login`.
- Protected routes also block access with `428 AUTH_KEYS_REQUIRED` until both global keys are set, except for the minimal safe paths used during initial setup.
- PUBLIC_REMOTE_PATHS (`/api/server/status|start|stop|restart`) accept the public bearer key; all other `/api/` routes require an authenticated session and optionally the admin bearer.
- The standalone public API server mirrors the remote control routes and always enforces the `AUTH_KEY` bearer. It is started and stopped alongside the control panel lifecycle.
