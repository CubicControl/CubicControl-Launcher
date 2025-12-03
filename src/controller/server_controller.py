import datetime
import logging
import os
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
    """Background watcher that mirrors the original controller logic per server profile."""

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
        self.server_back_online_status = None
        self.last_player_count = 0
        self.ready_to_sleep = False

    # ---- Core monitoring operations ----
    def get_player_info(self):
        """Get the number of players currently online using the query port."""
        try:
            server = JavaServer(self.profile.server_ip, self.profile.query_port)
            query = server.query()

            if self.server_offline_logged:
                self.logger.info("Server is back online. Polling will continue...")
                self.server_offline_logged = False

            if query.players.online > 0:
                self.server_empty_logged = False
                return query.players.online, query.players.names
            else:
                if not self.server_empty_logged:
                    self.logger.info("No players online. Polling will continue...")
                    self.server_empty_logged = True
                return 0, []

        except ConnectionError:
            if not self.server_offline_logged:
                self.logger.info("Server may be offline. Polling will continue...")
                self.server_offline_logged = True
            return None, []

    def send_rcon_command(self, command):
        try:
            with MCRcon(self.profile.server_ip, self.profile.rcon_password, port=self.profile.rcon_port) as mcr:
                response = mcr.command(command)
                self.logger.info(f"RCON response: {response}")
        except Exception as exc:  # pragma: no cover - defensive logging only
            self.logger.error(f"Error sending RCON command: {exc}")

    def stop_server(self):
        try:
            server = JavaServer(self.profile.server_ip, self.profile.query_port)
            query = server.query()
            if query.players.online is not None:
                self.send_rcon_command("stop")
        except ConnectionError as exc:  # pragma: no cover - defensive logging only
            self.logger.error(f"Error checking server status or sending RCON command: {exc}")

    def handle_server_online(self, player_count, players_list):
        if player_count is None:
            self.server_offline_logged = True
            self.last_player_count = 0

        if player_count == 0:
            self.server_offline_logged = False
            if not self.server_empty_logged:
                self.server_empty_logged = True
            self.last_player_count = 0

        if player_count is not None and player_count > 0:
            self.last_active_time = time.time()
            if player_count != self.last_player_count:
                self.logger.info(f"Player count changed: {player_count} - Players: {players_list}")
                self.last_player_count = player_count
            self.ready_to_sleep = False
            self.server_empty_logged = False
            self.server_offline_logged = False

        if int(time.time()) - self.last_active_time >= self.profile.inactivity_limit:
            self.logger.info(
                "No players online for the specified time limit: %s seconds. Stopping server...",
                self.profile.inactivity_limit,
            )
            self.stop_server()
            self.logger.info("Server stopped.")
            self.ready_to_sleep = True

    def monitor_server(self):
        self.logger.info("Starting Minecraft server monitoring for profile '%s'", self.profile.name)
        while not self.stop_event.is_set():
            if self.ready_to_sleep:
                self.send_command_shut_api()
                sleep(2)
                if self.profile.pc_sleep_after_inactivity:
                    self.logger.info("Shutting down the system...")
                    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
                break

            player_count, players_list = self.get_player_info()
            self.handle_server_online(player_count, players_list)
            time.sleep(self.profile.polling_interval)

    def send_command_shut_api(self):
        shutdown_key = self.profile.shutdown_key
        auth_key = self.profile.auth_key
        if not auth_key or not shutdown_key:
            self.logger.error("Missing shutdown/auth keys in profile '%s'", self.profile.name)
            return

        headers = {"Authorization": f"Bearer {auth_key}", "shutdown-header": shutdown_key}

        try:
            response = requests.post("http://localhost:37000/shutdown", headers=headers)
            self.logger.info(
                "Shutdown ServerSide API. Response: %s - Status code: %s", response.text, response.status_code
            )
            time.sleep(5)
        except Exception as exc:  # pragma: no cover - defensive logging only
            self.logger.error(f"Error sending shutdown request: {exc}")

    def start_in_thread(self) -> Thread:
        """Start monitoring in a separate daemon thread."""
        thread = Thread(target=self.monitor_server, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.stop_event.set()
