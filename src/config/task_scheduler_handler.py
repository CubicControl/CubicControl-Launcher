import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from src.logging_utils.logger import logger

DEFAULT_SCHEDULER_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Run CubicControl after resume</Description>
  </RegistrationInfo>
  <Triggers>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>__SCRIPT_DIR__</Command>
      <Arguments></Arguments>
    </Exec>
  </Actions>
</Task>
"""

def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as exc:
        logger.warning("Admin check failed: %s", exc)
        return False


class TaskSchedulerHandler:

    TASK_NAME = "CubicControl"

    def __init__(self, app_path: Path):
        self.app_path = Path(app_path)

    def _task_exists(self) -> bool:
        try:
            subprocess.run(
                ["schtasks", "/Query", "/TN", self.TASK_NAME],
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False
        except Exception as exc:
            logger.warning("Unable to check scheduled task: %s", exc)
            return False

    def _current_task_command(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", self.TASK_NAME, "/FO", "LIST", "/V"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in (result.stdout or "").splitlines():
                if "Task To Run" in line:
                    _, value = line.split(":", 1)
                    return value.strip().strip('"')
        except Exception as ex:
            logger.warning("Unable to get current scheduled task command: %s", ex)
            return None
        return None

    def _render_xml(self) -> Path:
        # Fill the template placeholder with the current executable path and return a temp XML path.
        content = DEFAULT_SCHEDULER_XML
        rendered = content.replace("__SCRIPT_DIR__", str(self.app_path))

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-16") as tmp:
            tmp.write(rendered)
            return Path(tmp.name)

    def _install_task(self) -> bool:
        xml_path: Optional[Path] = None
        try:
            xml_path = self._render_xml()
            subprocess.run(
                ["schtasks", "/Create", "/TN", self.TASK_NAME, "/XML", str(xml_path), "/F"],
                check=True,
            )
            logger.info("Scheduled task '%s' installed/updated.", self.TASK_NAME)
            return True
        except Exception as exc:
            logger.warning("Failed to install scheduled task '%s': %s", self.TASK_NAME, exc)
            return False
        finally:
            if xml_path:
                try:
                    xml_path.unlink(missing_ok=True)
                except Exception as exc:
                    logger.debug("Failed to delete temp XML file '%s': %s", xml_path, exc)

    def ensure_task(self) -> None:
        if not _is_windows():
            logger.info("Skipping scheduler setup: not running on Windows.")
            return
        if not self.app_path.exists():
            logger.warning("Skipping scheduler setup: app path does not exist: %s", self.app_path)
            return
        desired_command = str(self.app_path)
        current_command = self._current_task_command() if self._task_exists() else None
        needs_install = current_command != desired_command
        if needs_install:
            self._install_task()

    @staticmethod
    def check_admin_required_for_first_setup() -> bool:
        if not _is_windows():
            return True

        # Quick check if task exists without needing an instance
        try:
            subprocess.run(
                ["schtasks", "/Query", "/TN", TaskSchedulerHandler.TASK_NAME],
                capture_output=True,
                text=True,
                check=True,
            )
            # Task exists, no admin check needed
            return True
        except subprocess.CalledProcessError:
            # Task doesn't exist - check if we're admin
            if not _is_admin():
                logger.warning(
                    "Administrator privileges are required to create the CubicControl scheduled task on first setup. "
                    "Please run the application as an administrator."
                )
                try:
                    print("\nClose the terminal or press a key to exit...", flush=True)
                    input()
                except Exception as exc:
                    logger.debug("Input interrupted: %s", exc)
                return False
            return True
        except Exception as exc:
            logger.warning("Unable to check scheduled task: %s", exc)
            return True