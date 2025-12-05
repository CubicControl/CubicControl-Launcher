import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from time import sleep

import requests

GITHUB_API_LATEST = "https://api.github.com/repos/caddyserver/caddy/releases/latest"
data_folder = Path(__file__).parent.parent.parent / "data"
local_caddy_path = data_folder / "caddy.exe"

def _is_caddy_available() -> bool:
    # Check if "caddy" is on PATH
    caddy_on_path = shutil.which("caddy")

    # Fallback to local data folder if not on PATH
    if not caddy_on_path:
        if not local_caddy_path.exists():
            return False
        candidate_path = str(local_caddy_path)
    else:
        candidate_path = caddy_on_path

    try:
        subprocess.run(
            [candidate_path, "version"],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except Exception as e:
        print("Caddy found but failed to run:", e)
        return False

def _get_os_arch():
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
    """
    Pick the correct Caddy asset for the given OS and arch.
    Only return .zip or .tar.gz files.
    """
    for asset in assets:
        name = asset["name"].lower()
        if os_name in name and arch in name:
            if name.endswith(".zip") or name.endswith(".tar.gz"):
                print("Selected asset:", name)
                return asset
    return None


def download_latest_caddy(target_dir: Path) -> Path:
    """
    Download latest Caddy, extract it to target_dir, and return the path
    to the caddy binary.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Get latest release metadata
    resp = requests.get(GITHUB_API_LATEST, timeout=30)
    resp.raise_for_status()
    release = resp.json()

    assets = release.get("assets", [])
    os_name, arch = _get_os_arch()
    asset = find_caddy_asset_name(assets, os_name, arch)

    if not asset:
        raise RuntimeError(
            f"Could not find a Caddy release asset for {os_name}-{arch}"
        )

    download_url = asset["browser_download_url"]
    print(f"Downloading Caddy from: {download_url}")

    # 2. Download the archive
    archive_path = download_archive(download_url)

    # 3. Extract the archive
    extracted_caddy = extract_caddy_from_archive(archive_path, target_dir)

    # Remove the archive
    archive_path.unlink(missing_ok=True)

    if not extracted_caddy or not extracted_caddy.exists():
        raise RuntimeError("Failed to find caddy binary in archive")

    # On Unix, make it executable
    if os_name != "windows":
        extracted_caddy.chmod(extracted_caddy.stat().st_mode | 0o111)

    print("Caddy installed at:", extracted_caddy)
    print("Setting up Caddyfile...")
    write_caddyfile(target_dir)
    return extracted_caddy

def download_archive(download_url):
    ext = os.path.splitext(download_url)[1]  # Get extension from URL
    with requests.get(download_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    tmp_file.write(chunk)
            archive_path = Path(tmp_file.name)
            print("Downloaded archive to:", archive_path)
    return archive_path


def extract_caddy_from_archive(archive_path: Path, target_dir: Path) -> Path:
    extracted_caddy = None
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.infolist():
                if member.filename.endswith("caddy") or member.filename.endswith("caddy.exe"):
                    zf.extract(member, path=target_dir)
                    extracted_caddy = target_dir / member.filename
                    break
    elif archive_path.suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix == ".gz":
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                name = member.name
                if name.endswith("caddy") or name.endswith("caddy.exe"):
                    tf.extract(member, path=target_dir)
                    extracted_caddy = target_dir / member.name
                    break
    else:
        raise RuntimeError(f"Unexpected archive format: {archive_path}")
    return extracted_caddy


def run_caddy_external():
    print("Running Caddy in external terminal...")
    data_folder_path = Path(__file__).parent.parent.parent / "data"
    caddyfile_path = data_folder_path / "Caddyfile"

    print(f"Sending command: caddy run --config \"{caddyfile_path}\"")

    try:
        subprocess.Popen(
            ['cmd.exe', '/k', 'caddy', 'run', '--config', str(caddyfile_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as e:
        print("Failed to run Caddy in external terminal:", e)

def setup_caddy_env(caddy_path: Path):
    caddy_dir = str(caddy_path)
    current_path = os.environ.get("PATH", "")
    if caddy_dir not in current_path:
        os.environ["PATH"] = f"{caddy_dir};{current_path}"


def write_caddyfile(data_folder: Path):
    caddyfile_path = data_folder / "Caddyfile"
    caddyfile_content = """
jmgaming.chickenkiller.com {
    reverse_proxy 127.0.0.1:38000
}
    """
    with open(caddyfile_path, "w") as f:
        f.write(caddyfile_content)
    print("Caddyfile written to:", caddyfile_path)



if __name__ == "__main__":
    if not _is_caddy_available():
        print("Caddy not found, downloading...")
        caddy_binary = download_latest_caddy(Path(data_folder))
        print("Caddy setup complete. Ready to use.")

    # Always ensure Caddy directory is in PATH
    setup_caddy_env(data_folder)

    # Run Caddy in an external terminal
    run_caddy_external()
