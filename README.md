<p align="center">
  <img src="src/interface/static/CubicControlLogo.jpg" alt="CubicControl Logo" width="400"/>
</p>
<br>


CubicControl is a Windows-only control panel that makes running and sharing Minecraft servers with friends easy. It provides a single UI for common tasks: starting/stopping servers, monitoring activity, managing profiles, tunneling with PlayitGG, and auto-sleeping your PC on inactivity.

> ⚠️ **Disclaimer**
>
> **I am not a professional developer.** CubicControl started as a personal project that I decided to share in case others find it useful or enjoyable. While I have done my best to ensure the code is functional and free of major bugs, there may be inconsistencies or coding issues present.  
> **This is an ongoing project, and improvements or fixes will continue over time.**

## Key Features
- Manage multiple server profiles (vanilla or modpacks) with per-profile config.
- Start/stop server and controller processes, view live logs, and send commands.
- Automatic inactivity handling, with optional host PC sleep/app shutdown (ideal for a dedicated Windows box).
- PlayitGG integration for exposing your server to friends on the internet.
- Automatic download of Caddy reverse proxy to front the panel locally.
- A task scheduler is automatically set up to start the CubicControl panel when waking the PC from sleep.

## Remote Web Access (companion Flask frontend)
You can deploy the lightweight Flask frontend to a free Render account so friends can start/stop/wake the server PC without your direct involvement. This keeps the local control panel private while exposing only the actions you want to share.

## Requirements
- Windows 10/11.
- A wired ethernet connection (for Wake On Lan functionality).
- Java installed for the Minecraft server itself.
- A domain name for remote access to the panel.
- (Optional) PlayitGG installed; provide the full path to `playit.exe` in the UI when prompted.

## PlayitGG
PlayitGG is required to share your server over the internet. In the UI, set the full path to `playit.exe` (or a folder containing it). The panel can start/stop Playit for you once configured.

# Quick Start
1. Enable Wake On Lan in your PC BIOS settings.
2. Ensure your PC is connected via wired ethernet.
3. Enable Wake On Lan in your Windows network adapter settings.
4. Install Java if not already installed.
5. Download the latest CubicControl.exe release
6. Run CubicControl.exe
7. Access to panel on `http://localhost:38000/`
8. Create a password when prompted
9. Create a server profile (vanilla or modpack)
10. Activte the profile and start the server from the UI
11. (Optional) Configure PlayitGG for remote internet access to your Minecraft server
12. (Optional) Set up remote web access with [CubicControl Flask frontend](https://google.com)

At this point, your server should be running and accessible on your local network. If you set up PlayitGG, it should also be accessible over the internet.
The server is now fully autonomous and will handle inactivity/sleep as configured. After inactivity, the server and panel will stop, and your PC will sleep. Waking the PC will automatically start the panel again.

## Caddy Attribution
This application downloads and uses Caddy (https://caddyserver.com/), licensed under the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0).

## Documentation
There is a `docs/guide.html` with additional usage details.

## Support / Issues
If you encounter issues, include logs from `logs/` and steps to reproduce.
