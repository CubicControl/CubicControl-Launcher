import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path

from src.logging_utils.logger import logger

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent


# Current rule names (created by the bundled script)
CURRENT_RULES = {
    "CubicControl block inbound",
    "Caddy allow HTTP",
    "Caddy allow HTTPS",
}

# Legacy rule names to tolerate installs from previous versions
LEGACY_RULES = {
    "CubicControl - Block Control Panel (TCP-In)",
    "CubicControl - Block Public API (TCP-In)",
}

FIREWALL_SCRIPT = r"""param(
    [string]$CubicControlExe,
    [string]$CaddyExe
)

function Ensure-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        Write-Error "Run this script as Administrator."
        exit 1
    }
}

function Remove-ExistingRules {
    foreach ($name in @("CubicControl block inbound","Caddy allow HTTP","Caddy allow HTTPS")) {
        Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
}

function Add-Rule {
    param($Name, $Program, $Action, $Ports)

    if (-not (Test-Path $Program)) {
        Write-Warning "Program not found: $Program"
        return
    }

    $args = @{
        DisplayName = $Name
        Direction = 'Inbound'
        Program = $Program
        Action = $Action
        Enabled = 'True'
    }
    
    if ($Ports) {
        $args['Protocol'] = 'TCP'
        $args['LocalPort'] = $Ports
    }

    New-NetFirewallRule @args | Out-Null
}

Ensure-Admin
Remove-ExistingRules

if ($CubicControlExe) {
    Add-Rule -Name "CubicControl block inbound" -Program $CubicControlExe -Action Block -Ports $null
} else {
    Write-Warning "CubicControl executable path not provided"
}

if ($CaddyExe) {
    Add-Rule -Name "Caddy allow HTTP" -Program $CaddyExe -Action Allow -Ports 80
    Add-Rule -Name "Caddy allow HTTPS" -Program $CaddyExe -Action Allow -Ports 443
} else {
    Write-Warning "Caddy executable path not provided"
}

Write-Host "Firewall rules applied."
"""



def _rule_exists(rule_name: str) -> bool:
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
            capture_output=True,
            text=True,
        )
        return "No rules match the specified criteria" not in result.stdout
    except Exception as exc:
        logger.warning("Unable to check firewall rule '%s': %s", rule_name, exc)
        return False


def firewall_rules_missing() -> bool:
    """
    Return True if required firewall coverage is missing (Windows only).
    Accept either the current rule set or the legacy set.
    """
    if not sys.platform.startswith("win"):
        return False

    current_ok = all(_rule_exists(rule) for rule in CURRENT_RULES)
    legacy_ok = all(_rule_exists(rule) for rule in LEGACY_RULES)
    return not (current_ok or legacy_ok)


def firewall_debug_status() -> dict:
    """Return a debug dict of which rules exist (current and legacy)."""
    status = {
        "platform": sys.platform,
        "current_rules": {},
        "legacy_rules": {},
    }
    if not sys.platform.startswith("win"):
        return status
    status["current_rules"] = {rule: _rule_exists(rule) for rule in CURRENT_RULES}
    status["legacy_rules"] = {rule: _rule_exists(rule) for rule in LEGACY_RULES}
    return status


def _run_firewall_script(cubic_control_exe: str, caddy_exe: str = None) -> None:
    """Execute the PowerShell firewall configuration script."""
    script_path = Path(tempfile.gettempdir()) / "setup_firewall.ps1"
    script_path.write_text(FIREWALL_SCRIPT, encoding="utf-8")

    cmd = [
        "powershell.exe",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script_path),
        "-CubicControlExe", cubic_control_exe
    ]

    if caddy_exe:
        cmd.extend(["-CaddyExe", caddy_exe])

    subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def apply_firewall_rules() -> bool:
    """Apply firewall rules for CubicControl and Caddy."""

    try:
        # If rules already exist (current or legacy), skip reapplying to avoid admin prompt when not elevated
        if not firewall_rules_missing():
            return True

        # Get the CubicControl executable path
        cubic_exe = Path(sys.executable) if getattr(sys, "frozen", False) else None
        if not cubic_exe or not cubic_exe.exists():
            logger.error("Could not determine CubicControl executable path")
            return False

        # Get the Caddy executable path (hardcoded relative to the running executable)
        if getattr(sys, "frozen", False):
            # Running as frozen executable
            caddy_exe = Path(sys.executable).parent / "data" / "caddy.exe"
        else:
            # Running in development mode
            caddy_exe = Path(__file__).parent.parent.parent / "data" / "caddy.exe"

        if not caddy_exe.exists():
            logger.warning(f"Caddy executable not found at {caddy_exe}")
            caddy_exe = None
        else:
            caddy_exe = str(caddy_exe)

        # Run the PowerShell script with both paths
        _run_firewall_script(str(cubic_exe), caddy_exe)

        logger.info("Firewall rules applied successfully")
        return True
    except Exception as exc:
        logger.error(f"Failed to apply firewall rules: {exc}")
        return False




