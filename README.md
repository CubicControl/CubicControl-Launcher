<img src="CubicControlLogo.png" alt="CubicControl Logo" width="200"/>

CubicControl is a Windows-only control panel that makes running and sharing Minecraft servers with friends easy. It provides a single UI for common tasks: starting/stopping servers, monitoring activity, managing profiles, tunneling with PlayitGG, and auto-sleeping your PC on inactivity.

## Key Features
- Manage multiple server profiles (vanilla or modpacks) with per-profile config.
- Start/stop server and controller processes, view live logs, and send commands.
- Automatic inactivity handling, with optional host PC sleep/app shutdown (ideal for a dedicated Windows box).
- PlayitGG integration for exposing your server to friends on the internet.
- Automatic download of Caddy reverse proxy to front the panel locally.

## Remote Web Access (companion Flask frontend)
You can deploy the lightweight Flask frontend to a free Render account so friends can start/stop/wake the server PC without your direct involvement. This keeps the local control panel private while exposing only the actions you want to share.

## Requirements
- Windows 10/11.
- Java installed for the Minecraft server itself.
- (Optional) PlayitGG installed; provide the full path to `playit.exe` in the UI when prompted.
- (Optional) A domain name for remote access to the panel.

The panel starts at `http://localhost:38000/`. On first run you’ll be asked to create a password.

## PlayitGG
PlayitGG is required to share your server over the internet. In the UI, set the full path to `playit.exe` (or a folder containing it). The panel can start/stop Playit for you once configured.

# Quick Start
1. Download the latest CubicControl.exe release
2. Run CubicControl.exe
3. Create a password when prompted
4. Create a server profile (vanilla or modpack)
5. Start the server from the UI
6. (Optional) Configure PlayitGG for internet access
7. (Optional) Set up remote web access with the Flask frontend

## Caddy Attribution
This application downloads and uses Caddy (https://caddyserver.com/), licensed under the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0).

## Documentation
There is a `docs/guide.html` with additional usage details.

## Support / Issues
If you encounter issues, include logs from `logs/` and steps to reproduce.
