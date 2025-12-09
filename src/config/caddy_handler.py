import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
import requests

from src.logging_utils.logger import logger

GITHUB_API_LATEST = "https://api.github.com/repos/caddyserver/caddy/releases/latest"
CADDY_PROXY_TARGET = "127.0.0.1:38000"


def _get_os_arch() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system != "windows":
        raise OSError(f"Only Windows is supported, got: {system}")

    os_name = "windows"

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    return os_name, arch


def find_caddy_asset_name(assets, os_name, arch):
    # Pick the correct Caddy asset for the given OS and arch.
    for asset in assets:
        name = asset["name"].lower()
        if os_name in name and arch in name:
            if name.endswith(".zip") or name.endswith(".tar.gz"):
                logger.info("Selected Caddy asset: %s", name)
                return asset
    return None


def fetch_latest_release() -> dict:
    response = requests.get(GITHUB_API_LATEST, timeout=30)
    response.raise_for_status()
    return response.json()


def download_archive(download_url: str) -> Path:
    ext = os.path.splitext(download_url)[1]
    with requests.get(download_url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)
            archive_path = Path(tmp_file.name)
            logger.info("Downloaded Caddy archive to: %s", archive_path)
    return archive_path


def extract_caddy_from_archive(archive_path: Path, target_dir: Path) -> Path:
    extracted_caddy = None
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                if member.filename.endswith("caddy") or member.filename.endswith("caddy.exe"):
                    archive.extract(member, path=target_dir)
                    extracted_caddy = target_dir / member.filename
                    break
    elif archive_path.suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix == ".gz":
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                name = member.name
                if name.endswith("caddy") or name.endswith("caddy.exe"):
                    archive.extract(member, path=target_dir)
                    extracted_caddy = target_dir / member.name
                    break
    else:
        raise RuntimeError(f"Unexpected archive format: {archive_path}")
    return extracted_caddy


def download_latest_caddy(target_dir: Path, release_data: Optional[dict] = None) -> Path:
    # Download latest Caddy, extract it to target_dir, and return the path to the caddy binary.
    target_dir.mkdir(parents=True, exist_ok=True)

    release = release_data or fetch_latest_release()

    assets = release.get("assets", [])
    os_name, arch = _get_os_arch()
    asset = find_caddy_asset_name(assets, os_name, arch)

    if not asset:
        raise RuntimeError(f"Could not find a Caddy release asset for {os_name}-{arch}")

    download_url = asset["browser_download_url"]
    logger.info("Downloading Caddy from: %s", download_url)

    archive_path = download_archive(download_url)
    extracted_caddy = extract_caddy_from_archive(archive_path, target_dir)
    archive_path.unlink(missing_ok=True)

    if not extracted_caddy or not extracted_caddy.exists():
        raise RuntimeError("Failed to find caddy binary in archive")

    extracted_caddy.chmod(extracted_caddy.stat().st_mode | 0o111)
    logger.info("Caddy installed at: %s", extracted_caddy)
    return extracted_caddy


def _parse_version(version: str) -> Optional[tuple[int, ...]]:
    cleaned = version.strip()
    if not cleaned:
        return None
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    cleaned = cleaned.split()[0].split("-")[0]
    parts: list[int] = []
    for piece in cleaned.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) if parts else None


def _is_newer_version(latest: str, installed: str) -> bool:
    latest_parts = _parse_version(latest)
    installed_parts = _parse_version(installed)
    if not latest_parts or not installed_parts:
        return False
    max_len = max(len(latest_parts), len(installed_parts))
    latest_list = list(latest_parts) + [0] * (max_len - len(latest_parts))
    installed_list = list(installed_parts) + [0] * (max_len - len(installed_parts))
    return tuple(latest_list) > tuple(installed_list)


def _get_installed_version(binary_path: Path) -> Optional[str]:
    # Version probing is optional; avoid destabilizing running instances.
    try:
        _ensure_env_path(binary_path)
        result = subprocess.run(
            [str(binary_path), "version"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(binary_path.parent),
        )
        output = (result.stdout or result.stderr or "").strip()
        if not output:
            return None
        first_line = output.splitlines()[0].strip()
        if not first_line:
            return None
        return first_line.split()[0]
    except Exception as exc:
        logger.info("Skipping Caddy version read: %s", exc)
        return None


def _read_new_log_lines(log_path: Path, start_offset: int) -> tuple[list[str], int]:
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as log_file:
            log_file.seek(start_offset)
            data = log_file.read()
            new_position = log_file.tell()
            if not data:
                return [], new_position
            return data.splitlines(), new_position
    except Exception:
        return [], start_offset


def _ensure_env_path(caddy_path: Path) -> None:
    caddy_dir = str(caddy_path.parent)
    current_path = os.environ.get("PATH", "")
    if caddy_dir and caddy_dir not in current_path:
        os.environ["PATH"] = f"{caddy_dir};{current_path}"


def _validate_hostname(hostname: str) -> bool:
    if not hostname:
        return False
    hostname = hostname.strip().lower()
    if len(hostname) < 4 or len(hostname) > 253:
        return False
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-."
    if any(ch not in allowed for ch in hostname):
        return False
    if ".." in hostname or hostname.startswith("-") or hostname.endswith("-"):
        return False
    parts = hostname.split(".")
    if len(parts) < 2 or any(len(p) == 0 for p in parts):
        return False
    if any(len(p) > 63 for p in parts):
        return False
    return True


def _prompt_hostname() -> str:
    prompt = (
        "CADDY SETUP\n"
        "Enter your hostname address for Caddy to use (e.g., mc.example.com): "
    )
    while True:
        hostname = input(prompt).strip()
        if _validate_hostname(hostname):
            return hostname
        print("Invalid hostname. Please enter a valid domain (letters, numbers, dots, and dashes).")


def _verify_binary(candidate: Path) -> bool:
    try:
        _ensure_env_path(candidate)
        subprocess.run(
            [str(candidate), "version"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(candidate.parent),
        )
        return True
    except Exception as exc:
        logger.info("Caddy version check failed (continuing with existing binary): %s", exc)
        return False


def _is_warmup_proxy_error(line: str) -> bool:
        # Return True when the log line is just the upstream being down during startup.
    lower = line.lower()
    warmup_markers = (
        "reverseproxy.statuserror",
        "dial tcp",
        "connectex",
        "connection refused",
        "\"status\":502",
    )
    target_markers = (
        CADDY_PROXY_TARGET.lower(),
        "127.0.0.1:38000",
        "localhost:38000",
    )
    if not any(marker in lower for marker in warmup_markers):
        return False
    return any(target in lower for target in target_markers)


class CaddyManager:
    """Manage installation and lifecycle of the bundled Caddy reverse proxy."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent
            else:
                base = Path(__file__).resolve().parents[2]
            data_dir = base / "data"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.caddyfile_path = self.data_dir / "Caddyfile"
        self.local_caddy_path = self.data_dir / "caddy.exe"
        if getattr(sys, "frozen", False):
            self._log_dir = Path(sys.executable).parent / "logs"
        else:
            self._log_dir = Path(__file__).resolve().parents[2] / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file_path: Optional[Path] = None
        self._log_file_handle: Optional[object] = None
        self._log_thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._pid: Optional[int] = None
        self._binary_path: Optional[Path] = None
        self._hostname: Optional[str] = None
        self._last_start_errors: list[str] = []
        self._last_start_exit_code: Optional[int] = None
        self._last_start_log_tail: list[str] = []
        self._last_start_had_failure: bool = False

    def _discover_binary(self) -> Optional[Path]:
        # Prefer bundled/downloaded copy; avoid external shims that may spawn extra processes.
        if self._binary_path and Path(self._binary_path).exists():
            return Path(self._binary_path)
        if self.local_caddy_path.exists():
            return self.local_caddy_path
        candidate = shutil.which("caddy")
        if candidate and not getattr(sys, "frozen", False):
            # In dev, allow using PATH-based Caddy; in frozen builds always download local copy.
            return Path(candidate)
        return None

    def is_available(self) -> bool:
        # If we have a known binary path that still exists, trust it.
        if self._binary_path and Path(self._binary_path).exists():
            return True
        # If already running, treat as available and set the path if possible.
        running_pid = self._capture_running_pid()
        if running_pid:
            candidate = self._discover_binary()
            if candidate:
                self._binary_path = candidate
            return True
        # Prefer local bundled copy without strict version check to avoid repeated spawns.
        if self.local_caddy_path.exists():
            self._binary_path = self.local_caddy_path
            return True
        # In dev, allow PATH-based Caddy (best-effort).
        if not getattr(sys, "frozen", False):
            candidate = shutil.which("caddy")
            if candidate:
                self._binary_path = Path(candidate)
                return True
        return False

    def ensure_binary(self) -> Path:
        if self.is_available():
            return Path(self._binary_path)

        logger.info("Caddy not found locally, downloading the latest release...")
        release = fetch_latest_release()
        caddy_binary = download_latest_caddy(self.data_dir, release_data=release)
        self._binary_path = caddy_binary
        # Only write the Caddyfile on first install (or when missing)
        self._ensure_caddyfile()
        return caddy_binary

    def _ensure_caddyfile(self) -> None:
        if self.caddyfile_path.exists():
            return

        hostname = _prompt_hostname()
        self._hostname = hostname
        caddyfile_content = f"""
{hostname} {{
    reverse_proxy {CADDY_PROXY_TARGET}
}}
"""
        with open(self.caddyfile_path, "w", encoding="utf-8") as file:
            file.write(caddyfile_content.strip() + "\n")
        logger.info("Caddyfile written to: %s", self.caddyfile_path)

    def _check_for_updates(self, binary_path: Path) -> None:
        installed_version = _get_installed_version(binary_path)
        if not installed_version:
            return

        try:
            release = fetch_latest_release()
        except Exception as exc:
            logger.warning("Unable to fetch latest Caddy release info: %s", exc)
            return

        latest_version = release.get("tag_name")
        if not latest_version:
            return

        if not _is_newer_version(latest_version, installed_version):
            return

        try:
            logger.info("New Caddy version %s available (installed: %s), updating...", latest_version, installed_version)
            updated_binary = download_latest_caddy(self.data_dir, release_data=release)
            self._binary_path = updated_binary
            _ensure_env_path(updated_binary)
            logger.info("Caddy updated to version %s", latest_version)
        except Exception as exc:
            logger.warning("Failed to download Caddy update: %s", exc)

    def _capture_running_pid(self) -> Optional[int]:
        if self._process and self._process.poll() is None:
            self._pid = self._process.pid
            return self._pid

        if self._pid:
            try:
                proc = psutil.Process(self._pid)
                if proc.is_running():
                    return self._pid
            except Exception:
                self._pid = None

        # Best effort: find any running Caddy process
        try:
            for proc in psutil.process_iter(["name"]):
                name = proc.info.get("name") or ""
                if "caddy" in name.lower():
                    self._pid = proc.pid
                    return self._pid
        except Exception:
            pass

        return None

    def _resolve_log_path(self) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        self._log_file_path = self._log_dir / f"caddy_{today}.log"
        return self._log_file_path

    def _prepare_log_file(self) -> tuple[Path, int]:
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
            except Exception:
                pass
            self._log_file_handle = None
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._resolve_log_path()
        start_offset = 0
        if self._log_file_path.exists():
            start_offset = self._log_file_path.stat().st_size
        self._log_file_handle = open(self._log_file_path, "a", encoding="utf-8", buffering=1)
        separator = "=" * 80
        self._log_file_handle.write(f"\n{separator}\nCADDY START {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{separator}\n")
        self._log_file_handle.flush()
        return self._log_file_path, start_offset

    def _probe_startup(
        self,
        log_path: Path,
        start_offset: int,
        timeout_seconds: float,
    ) -> None:
        position = start_offset
        buffer: list[str] = []
        failure_lines: list[str] = []
        exit_code: Optional[int] = None
        start_time = time.monotonic()
        failure_markers = (
            "error",
            "failed",
            "authorization failed",
            "failed authorizations",
            "could not get certificate",
            "rateLimited",
        )

        while time.monotonic() - start_time < timeout_seconds:
            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                break

            new_lines, position = _read_new_log_lines(log_path, position)
            if new_lines:
                buffer.extend(new_lines)
                for line in new_lines:
                    lower = line.lower()
                    if any(marker in lower for marker in failure_markers):
                        if _is_warmup_proxy_error(lower):
                            continue
                        failure_lines.append(line)
                if failure_lines:
                    break
            time.sleep(0.2)

        # Final read to catch any last lines before reporting
        new_lines, position = _read_new_log_lines(log_path, position)
        if new_lines:
            buffer.extend(new_lines)
            for line in new_lines:
                lower = line.lower()
                if any(marker in lower for marker in failure_markers):
                    if _is_warmup_proxy_error(lower):
                        continue
                    failure_lines.append(line)

        self._last_start_log_tail = buffer[-20:]
        self._last_start_errors = failure_lines[-5:]
        self._last_start_exit_code = exit_code
        self._last_start_had_failure = bool(self._last_start_errors or (exit_code not in (None, 0)))

    def is_running(self) -> bool:
        return bool(self._capture_running_pid())

    def _start_log_thread(self) -> None:
        if not self._process:
            return

        def _pump():
            if not self._process or not self._process.stdout:
                return
            for raw in iter(self._process.stdout.readline, b""):
                if raw == b"":
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                timestamped = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}"
                try:
                    if self._log_file_handle:
                        self._log_file_handle.write(timestamped + "\n")
                        self._log_file_handle.flush()
                except Exception:
                    pass

        self._log_thread = threading.Thread(target=_pump, daemon=True)
        self._log_thread.start()

    def start(self, probe_for_errors: bool = False, probe_timeout: float = 45.0) -> bool:
        if self.is_running():
            self._last_start_errors = []
            self._last_start_exit_code = None
            self._last_start_log_tail = []
            self._last_start_had_failure = False
            logger.info("Caddy already running (PID %s); skipping start.", self._pid)
            return False

        binary_path = self.ensure_binary()
        self._ensure_caddyfile()
        _ensure_env_path(binary_path)

        log_path, start_offset = self._prepare_log_file()
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [str(binary_path), "run", "--config", str(self.caddyfile_path)]
        try:
            self._process = subprocess.Popen(
                command,
                creationflags=creationflags,
                cwd=str(binary_path.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._pid = self._process.pid
            self._last_start_errors = []
            self._last_start_exit_code = None
            self._last_start_log_tail = []
            self._last_start_had_failure = False

            self._start_log_thread()

            if probe_for_errors:
                self._probe_startup(log_path, start_offset, probe_timeout)

            logger.info("Caddy STARTED with PID %s", self._pid)
            return True
        except Exception as exc:
            logger.error("Failed to start Caddy: %s", exc)
            self._process = None
            self._pid = None
            if self._log_file_handle:
                try:
                    self._log_file_handle.close()
                except Exception:
                    pass
                self._log_file_handle = None
            raise

    def ensure_started(self) -> bool:
        try:
            started = self.start()
            return started or self.is_running()
        except Exception as exc:
            logger.warning("Unable to start Caddy automatically: %s", exc)
            return False

    def stop(self) -> bool:
        if not self.is_running():
            # Best-effort: try to kill by executable name/path even if we lost the PID
            killed = self._terminate_additional_processes(kill_all=True)
            self._process = None
            self._pid = None
            return bool(killed)

        pid = self._pid
        proc = self._process
        if proc:
            try:
                proc.send_signal(getattr(subprocess, "CTRL_BREAK_EVENT", signal.SIGTERM))
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            if self._log_thread:
                self._log_thread.join(timeout=2)
            self._log_thread = None
        else:
            try:
                psutil.Process(pid).terminate()
            except Exception:
                pass

        if self._log_file_handle:
            try:
                self._log_file_handle.close()
            except Exception:
                pass
            self._log_file_handle = None
        self._log_thread = None

        self._process = None
        self._pid = None
        logger.info("Caddy process STOPPED for PID %s", pid)
        # Best-effort: terminate any other Caddy processes spawned from the same binary
        self._terminate_additional_processes(kill_all=True)
        return True

    def _terminate_additional_processes(self, kill_all: bool = False) -> int:
        # Kill any stray Caddy processes that share the same executable path.
        terminated = 0
        try:
            target_path = str(Path(self._binary_path).resolve()) if self._binary_path else None
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    exe = proc.info.get("exe")
                    name = (proc.info.get("name") or "").lower()
                    same_exe = exe and target_path and str(Path(exe).resolve()) == target_path
                    is_caddy = "caddy" in name
                    if same_exe or (kill_all and is_caddy):
                        if self._pid and proc.pid == self._pid:
                            continue
                        proc.terminate()
                        terminated += 1
                except Exception:
                    continue
        except Exception:
            pass
        return terminated

    def status(self) -> dict:
        if not self._log_file_path:
            self._resolve_log_path()
        return {
            "running": self.is_running(),
            "pid": self._pid,
            "binary_path": str(self._binary_path) if self._binary_path else "",
            "available": self.is_available(),
            "caddyfile": str(self.caddyfile_path),
            "log_path": str(self._log_file_path),
            "last_start_errors": self._last_start_errors,
            "last_start_exit_code": self._last_start_exit_code,
            "last_start_log_tail": self._last_start_log_tail,
            "last_start_had_failure": self._last_start_had_failure,
        }


if __name__ == "__main__":
    manager = CaddyManager()
    manager.ensure_started()
