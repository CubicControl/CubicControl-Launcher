import datetime
import logging
import os
import subprocess
import time
from pathlib import Path
from threading import Event, Thread
from time import sleep
from typing import Optional

from mcstatus import JavaServer
from mcrcon import MCRcon
import requests

from src.interface.server_profiles import ServerProfile


class ServerController:
    """Background watcher that monitors server activity and manages shutdown."""

    def __init__(self, profile: ServerProfile, *, log_dir: Optional[Path] = None):
        self.profile = profile
        self.stop_event = Event()

        log_directory = log_dir or profile.controller_log_dir
        log_directory.mkdir(parents=True, exist_ok=True)
        log_file = log_directory / f"{datetime.date.today()}_MinecraftControllerLogs.log"

        self.logger = logging.getLogger(f'Controller-{profile.name}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

        if not any(isinstance(h, logging.FileHandler) and h.baseFilename == file_handler.baseFilename for h in self.logger.handlers):
            self.logger.addHandler(file_handler)

        self.last_active_time = time.time()
        self.server_offline_logged = False
        self.server_empty_logged = False
        self.last_player_count = 0
        self.inactivity_shutdown_triggered = False

    def get_player_info(self):
        """Get the number of players currently online using the query port."""
        try:
            server = JavaServer(self.profile.server_ip, self.profile.query_port)
            query = server.query()

            if self.server_offline_logged:
                self.logger.info("Server is back online. Polling will continue...")
                self.server_offline_logged = False

            player_count = query.players.online
            if player_count > 0:
                self.server_empty_logged = False
                return player_count, query.players.names
            else:
                if not self.server_empty_logged:
                    self.logger.info("Server is online but empty. Monitoring for inactivity...")
                    self.server_empty_logged = True
                return 0, []

        except Exception as exc:
            if not self.server_offline_logged:
                self.logger.warning(f"Cannot reach server (may be offline): {exc}")
                self.server_offline_logged = True
            return None, []

    def send_rcon_command(self, command):
        """Send RCON command to server."""
        try:
            with MCRcon(self.profile.server_ip, self.profile.rcon_password, port=self.profile.rcon_port) as mcr:
                response = mcr.command(command)
                self.logger.info(f"RCON command '{command}' sent. Response: {response}")
                return True
        except Exception as exc:
            self.logger.error(f"Error sending RCON command '{command}': {exc}")
            return False

    def stop_minecraft_server(self):
        """Attempt to stop the Minecraft server gracefully via RCON."""
        self.logger.info("Attempting to stop Minecraft server...")
        success = self.send_rcon_command("stop")
        if success:
            self.logger.info("Stop command sent successfully.")
            # Wait for server to shut down
            sleep(10)
        return success

    def check_inactivity_and_shutdown(self, player_count):
        """Check if server has been inactive and trigger shutdown sequence."""
        current_time = time.time()

        # Reset inactivity timer if players are online
        if player_count is not None and player_count > 0:
            self.last_active_time = current_time
            self.inactivity_shutdown_triggered = False
            if player_count != self.last_player_count:
                self.logger.info(f"Players online: {player_count}")
                self.last_player_count = player_count
            return False

        # Check for inactivity timeout
        inactive_duration = current_time - self.last_active_time

        if not self.inactivity_shutdown_triggered and inactive_duration >= self.profile.inactivity_limit:
            self.logger.info(
                f"Inactivity limit reached ({self.profile.inactivity_limit}s). "
                f"Server has been empty/offline for {int(inactive_duration)}s."
            )
            self.inactivity_shutdown_triggered = True

            # Stop the server if it's still running
            if player_count == 0:  # Server online but empty
                self.stop_minecraft_server()

            # Shut down API
            self.send_command_shut_api()
            sleep(3)

            # Sleep PC if configured
            if self.profile.pc_sleep_after_inactivity:
                self.logger.info("Initiating system sleep...")
                sleep(2)
                try:
                    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
                except Exception as exc:
                    self.logger.error(f"Failed to sleep system: {exc}")

            return True

        return False

    def monitor_server(self):
        """Main monitoring loop."""
        self.logger.info(
            f"Starting server monitoring for '{self.profile.name}' "
            f"(inactivity_limit={self.profile.inactivity_limit}s, "
            f"polling_interval={self.profile.polling_interval}s)"
        )

        while not self.stop_event.is_set():
            player_count, players_list = self.get_player_info()

            if self.check_inactivity_and_shutdown(player_count):
                self.logger.info("Shutdown sequence completed. Stopping controller.")
                break

            time.sleep(self.profile.polling_interval)

        self.logger.info("Controller stopped.")

    def send_command_shut_api(self):
        """Send shutdown command to the API."""
        shutdown_key = self.profile.shutdown_key
        auth_key = self.profile.auth_key
        if not auth_key or not shutdown_key:
            self.logger.warning("Missing shutdown/auth keys, skipping API shutdown")
            return

        headers = {"Authorization": f"Bearer {auth_key}", "shutdown-header": shutdown_key}

        try:
            response = requests.post("http://localhost:37000/shutdown", headers=headers, timeout=5)
            self.logger.info(f"API shutdown request sent. Status: {response.status_code}")
        except Exception as exc:
            self.logger.error(f"Error sending shutdown request to API: {exc}")

    def start_in_thread(self) -> Thread:
        """Start monitoring in a separate daemon thread."""
        thread = Thread(target=self.monitor_server, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Signal the controller to stop."""
        self.logger.info("Stop signal received")
        self.stop_event.set()
