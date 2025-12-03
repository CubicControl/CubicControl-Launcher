import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from src.minecraft import server_properties

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
PROFILES_PATH = DATA_DIR / "server_profiles.json"


@dataclass
class ServerProfile:
    """Represents a single Minecraft server or modpack installation."""

    name: str
    server_path: str                  # required, comes before any defaults
    server_ip: str = "localhost"
    run_script: str = "run.bat"
    rcon_password: str = ""
    rcon_port: int = 27001
    query_port: int = 27002
    auth_key: str = ""
    shutdown_key: str = ""
    inactivity_limit: int = 1800
    polling_interval: int = 60
    pc_sleep_after_inactivity: bool = True
    description: str = ""
    env_scope: str = "per_server"  # or "global"

    @property
    def root(self) -> Path:
        return Path(self.server_path)

    @property
    def run_script_path(self) -> Path:
        return self.root / self.run_script

    @property
    def controller_log_dir(self) -> Path:
        return self.root / "ControllerLogs"

    @property
    def server_properties_path(self) -> Path:
        return self.root / "server.properties"

    def has_server_properties(self) -> bool:
        return self.server_properties_path.exists()

    @property
    def minecraft_logs_dir(self) -> Path:
        return self.root / "logs"

    def latest_minecraft_log(self) -> Optional[Path]:
        primary = self.minecraft_logs_dir / "latest.log"
        if primary.exists():
            return primary
        if not self.minecraft_logs_dir.exists():
            return None
        try:
            log_files = sorted(
                (p for p in self.minecraft_logs_dir.glob("*.log") if p.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        return log_files[0] if log_files else None

    def sync_server_properties(self) -> None:
        """Ensure core RCON/query settings are written to server.properties."""

        base_settings = {
            "enable-rcon": "true",
            "rcon.port": str(self.rcon_port),
            "rcon.password": self.rcon_password,
            "enable-query": "true",
            "query.port": str(self.query_port),
            "server-ip": self.server_ip,
        }

        self.server_properties_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.server_properties_path.exists():
            self.server_properties_path.write_text("# Minecraft server properties\n", encoding="utf-8")

        server_properties.write_server_properties(str(self.server_properties_path), base_settings)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["server_path"] = str(self.root)
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "ServerProfile":
        return cls(**data)

    def ensure_scaffold(self) -> None:
        """Create minimal folders/files for a managed server directory."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.controller_log_dir.mkdir(exist_ok=True)
        if not self.run_script_path.exists():
            self.run_script_path.write_text(
                "@echo off\n"
                "REM Place your server.jar next to this script and customise as needed.\n"
                "java -jar server.jar nogui\n",
                encoding="utf-8",
            )
        self.sync_server_properties()


class ServerProfileStore:
    """JSON-backed storage for multiple server installations."""

    def __init__(self, path: Path = PROFILES_PATH):
        self.path = path
        self.active_profile_name: Optional[str] = None
        self._profiles: Dict[str, ServerProfile] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.active_profile_name = data.get("active")
        profiles_data = data.get("profiles", {})
        for name, profile_data in profiles_data.items():
            self._profiles[name] = ServerProfile.from_dict(profile_data)

    def _save(self) -> None:
        payload = {
            "active": self.active_profile_name,
            "profiles": {name: profile.to_dict() for name, profile in self._profiles.items()},
        }
        self.path.parent.mkdir(exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def list_profiles(self) -> List[ServerProfile]:
        return list(self._profiles.values())

    def get_profile(self, name: str) -> Optional[ServerProfile]:
        return self._profiles.get(name)

    def upsert_profile(self, profile: ServerProfile) -> ServerProfile:
        profile.ensure_scaffold()
        profile.sync_server_properties()
        self._profiles[profile.name] = profile
        if not self.active_profile_name:
            self.active_profile_name = profile.name
        self._save()
        return profile

    def set_active(self, name: str) -> ServerProfile:
        if name not in self._profiles:
            raise KeyError(f"Profile '{name}' does not exist")
        self.active_profile_name = name
        profile = self._profiles[name]
        profile.ensure_scaffold()
        profile.sync_server_properties()
        self._save()
        return profile

    @property
    def active_profile(self) -> Optional[ServerProfile]:
        if not self.active_profile_name:
            return None
        return self._profiles.get(self.active_profile_name)

    def delete_profile(self, name: str) -> None:
        if name in self._profiles:
            del self._profiles[name]
            if self.active_profile_name == name:
                self.active_profile_name = next(iter(self._profiles), None)
            self._save()

    def update_properties(self, name: str, updates: Dict[str, str]) -> Dict[str, str]:
        profile = self.get_profile(name)
        if not profile:
            raise KeyError(f"Profile '{name}' does not exist")

        profile.ensure_scaffold()
        server_properties.write_server_properties(str(profile.server_properties_path), updates)
        return server_properties.parse_server_properties(str(profile.server_properties_path))

    def read_properties(self, name: str) -> Dict[str, str]:
        profile = self.get_profile(name)
        if not profile:
            raise KeyError(f"Profile '{name}' does not exist")
        profile.ensure_scaffold()
        return server_properties.parse_server_properties(str(profile.server_properties_path))
