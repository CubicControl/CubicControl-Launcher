import datetime
import logging
import os
import subprocess
import time
from pathlib import Path
from threading import Event, Thread
from time import sleep
from typing import Callable, Optional

import psutil
from mcrcon import MCRcon
from mcstatus import JavaServer

from src.interface.server_profiles import ServerProfile


class ServerController:
    """Background watcher that monitors server activity and manages shutdown."""

    def __init__(
        self,
        profile: ServerProfile,
        *,
        log_dir: Optional[Path] = None,
        shutdown_callback: Optional[Callable[[str], None]] = None,
    ):
        self.profile = profile
        self.stop_event = Event()
        self.shutdown_callback = shutdown_callback

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
        self.has_ever_seen_online = False
        self._app_shutdown_scheduled = False

    def get_player_info(self):
        """Get the number of players currently online using the query port."""
        try:
            server = JavaServer(self.profile.server_ip, self.profile.query_port)
            query = server.query()

            if self.server_offline_logged:
                self.logger.info("Server is back online. Polling will continue...")
                self.server_offline_logged = False
            self.has_ever_seen_online = True

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
                level = self.logger.info if not self.has_ever_seen_online else self.logger.warning
                friendly = (
                    "Server not reachable (likely offline or starting). "
                    f"Will keep polling; inactivity shutdown only after {self.profile.inactivity_limit}s idle."
                )
                level(f"{friendly} Details: {exc}")
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

            # Sleep PC if configured
            if self.profile.pc_sleep_after_inactivity:
                self.logger.info("Queuing system sleep after control panel exits...")
                self._schedule_sleep_after_exit()

            # Terminate the hosting process if configured
            if getattr(self.profile, "shutdown_app_after_inactivity", False):
                self.logger.info("Inactivity limit reached - shutting down control panel process.")
                self._schedule_app_termination()

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
                self.stop_controller()

            time.sleep(self.profile.polling_interval)

        self.logger.info("Controller stopped.")


    def start_in_thread(self) -> Thread:
        """Start monitoring in a separate daemon thread."""
        thread = Thread(target=self.monitor_server, daemon=True)
        thread.start()
        return thread

    def stop_controller(self):
        """Signal the controller to stop."""
        self.logger.info("Stop signal received")
        self.stop_event.set()

    # ----- Application termination helpers -----
    def _schedule_app_termination(self, delay: float = 2.0) -> None:
        """Terminate the hosting process after an optional delay to flush logs."""
        if self._app_shutdown_scheduled:
            return
        self._app_shutdown_scheduled = True
        Thread(target=self._terminate_host_application, args=(delay,), daemon=True).start()

    def _schedule_sleep_after_exit(self, delay_seconds: float = 2.0) -> None:
        """Spawn a helper that waits for this process to exit, then sleeps the PC."""
        if getattr(self, "_sleep_scheduled", False):
            return
        self._sleep_scheduled = True
        pid = os.getpid()
        script = (
            f"while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
            "{ Start-Sleep -Milliseconds 500 }; "
            f"Start-Sleep -Seconds {delay_seconds}; "
            "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
        )
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.logger.error(f"Failed to schedule system sleep: {exc}")

    def _terminate_host_application(self, delay: float) -> None:
        """Close the control panel process, preferring graceful cleanup first."""
        if delay:
            sleep(delay)

        try:
            current = psutil.Process(os.getpid())
            self.logger.info("Closing CubicControl due to inactivity. PID: %s", current.pid)

            # Prefer reusing the main app cleanup so Playit, Caddy, etc. are stopped cleanly
            if self.shutdown_callback:
                try:
                    self.shutdown_callback("inactivity")
                except Exception as exc:
                    self.logger.warning("Shutdown callback raised an exception: %s", exc)

            # Give the cleanup callback a brief window to finish shutting down
            # Playit, Caddy, and the Minecraft server before forcing the exit.
            self._wait_for_child_processes(current)

        except Exception as exc:
            self.logger.error(f"Failed to terminate CubicControl process: {exc}")
        finally:
            # os._exit ensures the process exits even if threads are still running
            os._exit(0)

    def _wait_for_child_processes(self, current: psutil.Process, grace_seconds: float = 5.0) -> None:
        """Wait briefly for any child processes to stop after cleanup."""
        try:
            children = current.children(recursive=True)
        except Exception as exc:
            self.logger.debug("Unable to enumerate child processes: %s", exc)
            return

        if not children:
            return

        deadline = time.time() + grace_seconds
        self.logger.info(
            "Waiting up to %.1fs for %d child process(es) to exit after cleanup...",
            grace_seconds,
            len(children),
        )

        while time.time() < deadline:
            try:
                if not any(child.is_running() for child in children):
                    return
            except Exception:
                return
            sleep(0.2)
