<p align="center">
  <img src="src/interface/static/CubicControlLogo.jpg" alt="CubicControl Logo" width="400"/>
</p>
<br>

CubicControl is the dedicated Windows control panel built to make hosting Minecraft servers easy — especially on a spare or dedicated PC.  
It lets you run, manage, and share your server with friends effortlessly, with built-in tools for automation, remote wake/start, Playit.gg tunneling, and more.

It is **designed to work together with the companion web frontend, [CubicControl-ClientSide](https://github.com/CubicControl/CubicControl-ClientSide)**,
allowing remote waking, starting, and monitoring of your Minecraft server from anywhere.

It provides a single UI for common tasks: starting/stopping servers, monitoring activity, managing profiles, tunneling with PlayitGG, and auto-sleeping your PC on inactivity.

> ⚠️ **Disclaimer**
>
> **I am not a professional developer.** CubicControl started as a personal project that I decided to share in case others find it useful or enjoyable.  
> While I have done my best to ensure the code is functional and free of major bugs, there may be inconsistencies or coding issues present.  
> **This is an ongoing project, and improvements or fixes will continue over time.**

## Key Features
- Manage multiple server profiles (vanilla or modpacks) with per-profile config.
- Start/stop server and controller processes, view live logs, and send commands.
- Automatic inactivity handling, with optional host PC sleep/app shutdown (ideal for a dedicated Windows box).
- PlayitGG integration for exposing your server to friends on the internet.
- Automatic download of Caddy reverse proxy to front the panel locally.
- A task scheduler is automatically set up to start the CubicControl panel when waking the PC from sleep.

## Remote Web Access (companion Flask frontend)
You can deploy the lightweight Flask frontend to a free Render account so friends can start/stop/wake the server PC without your direct involvement.  
This keeps the local control panel private while exposing only the actions you want to share.

**CubicControl-Launcher works hand-in-hand with:**  
➡️ **[CubicControl-ClientSide](https://github.com/CubicControl/CubicControl-ClientSide)**

## Requirements
- Windows 10/11.
- A wired ethernet connection (for Wake On Lan functionality).
- Java installed for the Minecraft server itself.
- A domain name for remote access to the panel. You can get a free one from https://freedns.afraid.org/ in Subdomains section.
- (Optional) PlayitGG installed; provide the full path to `playit.exe` in the UI when prompted.

## PlayitGG
PlayitGG is required to share your server over the internet.  
In the UI, set the full path to `playit.exe` (or a folder containing it).  
The panel can start/stop Playit for you once configured.

# Quick Start
1. Enable Wake On Lan in your PC BIOS settings.
2. Ensure your PC is connected via wired ethernet.
3. Enable Wake On Lan in your Windows network adapter settings.
4. Install Java if not already installed.
5. Set up port forwarding on your router to forward TCP ports **80** and **443** to your hosting PC's local IP address (required for Caddy to provide remote access), and UDP port **9** to allow remote Wake On Lan.
6. Download the latest CubicControl.exe release [HERE](https://github.com/romaingrude/CubicControl-Launcher/releases)
7. **⚠️ Run `CubicControl.exe` in Administrator mode the first time to allow it to set up the scheduled task.**
8. Access the panel on `http://localhost:38000/`
9. Create a password when prompted
10. Create a server profile (vanilla or modpack)
11. Activate the profile and start the server from the UI
12. (Optional) Configure PlayitGG for remote internet access to your Minecraft server
13. (Optional) Set up remote web access with [CubicControl-ClientSide](https://github.com/cubiccontrol/CubicControl-ClientSide.git)

At this point, your server should be running and accessible on your local network. If you set up PlayitGG, it should also be accessible over the internet.  
The server is now fully autonomous and will handle inactivity/sleep as configured. After inactivity, the server and panel will stop, and your PC will sleep.  
Waking the PC will automatically start the panel again.

---

# 📘 Full Installation & Setup Guide (Highly Recommended)

A complete step-by-step guide — covering BIOS setup, Wake-on-LAN, port forwarding, PlayitGG, launcher setup, and deployment of ClientSide — is available here:

➡️ **https://cubiccontrol.github.io/**  

This is the most up-to-date and beginner-friendly walkthrough of the entire ecosystem.

---

## Caddy Attribution
This application downloads and uses Caddy (https://caddyserver.com/), licensed under the Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0).

## Support / Issues
If you encounter issues, include logs from `logs/` and steps to reproduce.
