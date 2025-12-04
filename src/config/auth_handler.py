"""
Authentication handler for the control panel.
Manages secure password storage and verification.
"""
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Optional


class AuthHandler:
    """Handle authentication for the control panel."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the auth handler.

        Args:
            data_dir: Directory to store auth data. If None, uses ./data
        """
        if data_dir is None:
            # Use the data directory relative to the executable or script location
            if getattr(sys, 'frozen', False):
                # Running as exe
                base = Path(sys.executable).parent
            else:
                # Running as script
                base = Path(__file__).resolve().parent.parent.parent
            data_dir = base / "data"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.auth_file = self.data_dir / "auth.json"

    def _hash_password(self, password: str, salt: str) -> str:
        """Hash a password with a salt using SHA-256."""
        return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()

    def has_password(self) -> bool:
        """Check if a password has been set."""
        return self.auth_file.exists()

    def set_password(self, password: str) -> bool:
        """Set or update the password.

        Args:
            password: The password to set

        Returns:
            True if successful
        """
        if not password or len(password.strip()) < 4:
            raise ValueError("Password must be at least 4 characters")

        salt = secrets.token_hex(16)
        hashed = self._hash_password(password, salt)

        auth_data = {
            "password_hash": hashed,
            "salt": salt
        }

        with open(self.auth_file, 'w') as f:
            json.dump(auth_data, f, indent=2)

        return True

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash.

        Args:
            password: The password to verify

        Returns:
            True if password matches, False otherwise
        """
        if not self.has_password():
            return False

        try:
            with open(self.auth_file, 'r') as f:
                auth_data = json.load(f)

            stored_hash = auth_data.get("password_hash")
            salt = auth_data.get("salt")

            if not stored_hash or not salt:
                return False

            computed_hash = self._hash_password(password, salt)
            return computed_hash == stored_hash
        except Exception:
            return False

