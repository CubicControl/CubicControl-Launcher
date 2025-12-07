import base64
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - optional dependency
    Fernet = None


def _default_data_dir() -> Path:
    """Resolve the shared data directory, handling frozen executables."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "data"


class SecretStore:
    """Persist and retrieve auth secrets with light encryption."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = self.data_dir / "auth_keys.key"
        self.secrets_path = self.data_dir / "auth_keys.bin"
        self._fernet = self._load_fernet()
        self._cache: Optional[Dict[str, str]] = None

    def _load_fernet(self):
        if not Fernet:
            return None
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
        return Fernet(key)

    def _encode(self, payload: bytes) -> bytes:
        if self._fernet:
            return self._fernet.encrypt(payload)
        return base64.urlsafe_b64encode(payload)

    def _decode(self, payload: bytes) -> bytes:
        if self._fernet:
            return self._fernet.decrypt(payload)
        return base64.urlsafe_b64decode(payload)

    def _read(self) -> Dict[str, str]:
        if self._cache is not None:
            return dict(self._cache)
        if not self.secrets_path.exists():
            self._cache = {}
            return {}
        try:
            raw = self.secrets_path.read_bytes()
            decoded = self._decode(raw)
            data = json.loads(decoded.decode("utf-8"))
            self._cache = {k: str(v) for k, v in data.items()}
            return dict(self._cache)
        except Exception:
            # Corrupt or unreadable secrets should not crash the panel
            self._cache = {}
            return {}

    def get_keys(self) -> Tuple[str, str]:
        """Return (admin_auth_key, auth_key) as plain strings."""
        data = self._read()
        return data.get("admin_auth_key", "") or "", data.get("auth_key", "") or ""

    def has_keys(self) -> bool:
        admin, auth = self.get_keys()
        return bool(admin and auth)

    def save_keys(self, admin_auth_key: str, auth_key: str) -> None:
        """Persist the provided keys, overwriting any existing values."""
        admin_auth_key = (admin_auth_key or "").strip()
        auth_key = (auth_key or "").strip()
        if not admin_auth_key or not auth_key:
            raise ValueError("Both ADMIN_AUTH_KEY and AUTH_KEY are required.")

        payload = json.dumps(
            {"admin_auth_key": admin_auth_key, "auth_key": auth_key},
            ensure_ascii=True,
        ).encode("utf-8")

        encoded = self._encode(payload)
        tmp_path = self.secrets_path.with_suffix(".tmp")
        tmp_path.write_bytes(encoded)
        os.replace(tmp_path, self.secrets_path)
        self._cache = {"admin_auth_key": admin_auth_key, "auth_key": auth_key}

    def reset_cache(self) -> None:
        """Drop in-memory cache to force a reload on next read."""
        self._cache = None
